"""Usage source selection and the versioned, safe custom-command contract."""
import json, os, subprocess, time, math, selectors, signal, hashlib, plistlib
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler
from . import state
from datetime import datetime, timezone

VALID_SOURCES = ("auto", "native", "none", "off", "claude-usage-tracker",
                 "codex-app-server", "anthropic-admin", "openai-admin",
                 "experimental-claude-oauth", "experimental-codex-api")

def _safe_text(value, maximum=128):
    if not isinstance(value, str) or not value or len(value) > maximum: return None
    if any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value): return None
    return value

MIN_EPOCH, MAX_EPOCH = 0.0, 4102444800.0  # 1970 through 2100: reject nonsense

def epoch(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try: value = float(value)
        except (TypeError, ValueError, OverflowError): return None
        return value if math.isfinite(value) and MIN_EPOCH <= value <= MAX_EPOCH else None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            stamp = (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)).timestamp()
            return stamp if MIN_EPOCH <= stamp <= MAX_EPOCH else None
        except (ValueError, OverflowError, OSError): pass
    return None

def _number(value, upper=None):
    if isinstance(value, bool): return None
    try: value=float(value)
    except (TypeError, ValueError, OverflowError): return None
    if not math.isfinite(value) or value < 0 or (upper is not None and value > upper): return None
    return value

def _tokens(value):
    value=value if isinstance(value, dict) else {}
    names=("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
    out={name:_number(value.get(name)) for name in names}
    # Cached read is a subset of input; creation is input but not cache-read.
    if out["input_tokens"] is not None and out["cached_input_tokens"] is not None and out["cached_input_tokens"] > out["input_tokens"]: return {}
    if out["output_tokens"] is not None and out["reasoning_output_tokens"] is not None and out["reasoning_output_tokens"] > out["output_tokens"]: return {}
    return {key: val for key, val in out.items() if val is not None}

def normalise(value, source=""):
    """Whitelist the v1 source fields; malformed numbers are unavailable."""
    if (not isinstance(value, dict) or isinstance(value.get("schema_version"), bool)
            or value.get("schema_version") != 1): return {}
    wins=[]
    raw_buckets = value.get("buckets")
    # Buckets are canonical.  Do not combine them with an old flat shadow,
    # since a cached canonical result can otherwise double every quota.
    if raw_buckets is not None:
        if not isinstance(raw_buckets, list): return {}
        windows = []
        for bucket in raw_buckets:
            if not isinstance(bucket, dict): continue
            bucket_id = _safe_text(bucket.get("id"), 128)
            nested = bucket.get("windows")
            if bucket_id is None or not isinstance(nested, list): continue
            for nested_window in nested:
                if isinstance(nested_window, dict):
                    copy = dict(nested_window); copy["bucket_id"] = bucket_id
                    if "label" in bucket and "heading" not in copy: copy["heading"] = bucket["label"]
                    for field in ("model", "feature"):
                        if field in bucket and field not in copy: copy[field] = bucket[field]
                    windows.append(copy)
    else:
        windows = value.get("windows", [])
        if not isinstance(windows, list): return {}
        windows = [dict(window) for window in windows if isinstance(window, dict)]
    for w in windows:
        if not isinstance(w, dict): continue
        ident=_safe_text(w.get("id"))
        if ident is None: continue
        pct=_number(w.get("used_percent"), 100)
        duration=_number(w.get("duration_seconds"))
        item={"id":ident, "duration_seconds":duration, "used_percent":pct, "resets_at":epoch(w.get("resets_at"))}
        for field, maximum in (("bucket_id", 128), ("heading", 128), ("model", 128), ("feature", 128)):
            safe = _safe_text(w.get(field), maximum)
            if safe is not None: item[field] = safe
        # Missing usage is a valid quota window; it is not invented as zero.
        wins.append(item)
    account = value.get("account") if isinstance(value.get("account"), dict) else {}
    safe_account = {}
    for name in ("period_start", "period_end"):
        if epoch(account.get(name)) is not None: safe_account[name]=epoch(account[name])
    safe_account.update(_tokens(account))
    cost=_number(account.get("cost_usd"))
    if cost is not None: safe_account["cost_usd"]=cost
    scope=_safe_text(account.get("scope"), 64)
    if scope is not None: safe_account["scope"]=scope
    if safe_account.get("period_start") is not None and safe_account.get("period_end") is not None and safe_account["period_end"] < safe_account["period_start"]: return {}
    grouped = {}
    for window in wins:
        bucket_id = window.get("bucket_id") or "default"
        bucket = grouped.setdefault(bucket_id, {"id": bucket_id, "label": window.get("heading") or "default", "windows": []})
        for field in ("model", "feature"):
            if window.get(field) is not None: bucket[field] = window[field]
        child = {key: val for key, val in window.items() if key not in ("bucket_id", "heading", "model", "feature")}
        bucket["windows"].append(child)
    return {"schema_version": 1, "source": source, "as_of": epoch(value.get("as_of")), "buckets": list(grouped.values()),
            "account": safe_account}

def has_reading(value):
    """An envelope alone is not a source response and must not replace cache."""
    if not isinstance(value, dict): return False
    account = value.get("account") if isinstance(value.get("account"), dict) else {}
    for bucket in value.get("buckets", []) if isinstance(value.get("buckets"), list) else []:
        for window in bucket.get("windows", []) if isinstance(bucket, dict) and isinstance(bucket.get("windows"), list) else []:
            if _number(window.get("used_percent")) is not None:
                return True
    return any(_number(account.get(name)) is not None
               for name in ("input_tokens", "cached_input_tokens", "output_tokens",
                            "reasoning_output_tokens", "cost_usd"))

def _cached_reading(value, source, now, ttl):
    """Re-whitelist cache content and make stale/expired state visible."""
    clean = normalise(value, source)
    if not has_reading(clean): return {}
    as_of = epoch(value.get("as_of"))
    clean["as_of"] = as_of
    clean["stale"] = as_of is None or now - as_of >= ttl
    for name in ("fetched_at", "attempted_at", "retry_at", "fail_count"):
        n = _number(value.get(name))
        if n is not None: clean[name] = n
    # A quota whose reset has passed is historical, not a live availability.
    for bucket in clean.get("buckets", []):
        for window in bucket.get("windows", []):
            reset = window.get("resets_at")
            if reset is not None and reset <= now: window["expired"] = True
    return clean

def _refresh_due(raw_cache, now, ttl):
    """Refresh cadence follows fetch time, never an old provider observation."""
    retry_at = _number(raw_cache.get("retry_at")) if isinstance(raw_cache, dict) else None
    if retry_at is not None and now < retry_at:
        return False
    fetched = _number(raw_cache.get("fetched_at")) if isinstance(raw_cache, dict) else None
    return fetched is None or now - fetched >= ttl

def _failure_cache(raw_cache, now, ttl, retry_after=None):
    value = dict(raw_cache) if isinstance(raw_cache, dict) else {}
    count = int(_number(value.get("fail_count")) or 0) + 1
    delay = min(300.0, float(2 ** min(count, 8)))
    if retry_after is not None:
        delay = min(300.0, max(delay, retry_after))
    value.update({"attempted_at": now, "fail_count": count,
                  "retry_at": now + delay, "fetched_at": value.get("fetched_at")})
    return value

def _tag_identity(reading, agent, source, namespace, period_key):
    """Attach non-secret scope to every returned normalized reading."""
    if not isinstance(reading, dict) or not reading: return reading
    tagged = dict(reading)
    tagged.update({"agent": agent, "source": source or tagged.get("source", ""),
                   "account_name": namespace, "period_start": period_key})
    return tagged

def command_reading(path, context, timeout=5):
    """Run exactly one path (or bash fallback), passing no secrets or text."""
    path = os.path.abspath(path)
    if not os.path.isfile(path): return {}
    command = [path] if os.access(path, os.X_OK) else ["bash", path]
    selector = None
    proc = None
    try:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,
                                start_new_session=True)
        context = context if isinstance(context, dict) else {}
        safe_context = {}
        for key in ("agent", "session", "model", "account", "period"):
            text = _safe_text(context.get(key), 256)
            if text is not None: safe_context[key] = text
        for key in ("period_start", "period_end"):
            value = epoch(context.get(key))
            if value is not None: safe_context[key] = value
        proc.stdin.write(json.dumps(safe_context, separators=(",", ":")).encode("utf-8")); proc.stdin.close()
        deadline = time.monotonic() + max(.01, timeout); output = bytearray()
        selector = selectors.DefaultSelector(); selector.register(proc.stdout.fileno(), selectors.EVENT_READ)
        while time.monotonic() < deadline:
            ready = selector.select(max(0, deadline - time.monotonic()))
            if not ready: break
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk: break
            output.extend(chunk)
            if len(output) > 1024 * 1024: raise ValueError("command output too large")
        # EOF only closes stdout.  Give a short-lived process the remaining
        # shared deadline to finish rather than calling it a timeout at once.
        if proc.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise subprocess.TimeoutExpired(command, timeout)
            try: proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired: raise
        if proc.returncode: return {}
        value=json.loads(output.decode("utf-8"))
        if isinstance(value, dict) and "schema_version" not in value and any(key in value for key in ("session_pct", "weekly_pct", "session_resets_at", "weekly_resets_at")):
            # old flat adapter
            value={"schema_version": 1, "as_of": value.get("as_of"), "windows": [
                {"id":"session", "used_percent": value.get("session_pct"), "resets_at": value.get("session_resets_at")},
                {"id":"week", "used_percent": value.get("weekly_pct"), "resets_at": value.get("weekly_resets_at")}]}
        return normalise(value, "cmd")
    except subprocess.TimeoutExpired:
        try: os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, AttributeError): pass
        try: proc.communicate(timeout=1)
        except Exception: pass
        return {}
    except (OSError, ValueError, UnicodeDecodeError):
        if 'proc' in locals() and proc is not None and proc.poll() is None:
            try: os.killpg(proc.pid, signal.SIGKILL); proc.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired): pass
        return {}
    finally:
        if selector is not None:
            try: selector.close()
            except Exception: pass
        if proc is not None:
            try: proc.stdout.close()
            except (OSError, AttributeError): pass

def validate_source(agent, spec):
    spec = spec or "auto"
    if spec.startswith("cmd:"): return spec
    if spec not in VALID_SOURCES: raise ValueError("unknown usage source %r" % spec)
    if agent == "claude" and spec in ("codex-app-server", "openai-admin", "experimental-codex-api"):
        raise ValueError("%s is a Codex source" % spec)
    if agent == "codex" and spec in ("claude-usage-tracker", "anthropic-admin", "experimental-claude-oauth"):
        raise ValueError("%s is a Claude source" % spec)
    return spec

def _retry_after(value, now=None):
    if value is None: return None
    seconds = _number(value)
    if seconds is not None: return seconds
    try:
        stamp = epoch(value)
        if stamp is None and isinstance(value, str):
            stamp = parsedate_to_datetime(value).astimezone(timezone.utc).timestamp()
        return max(0.0, stamp - (time.time() if now is None else now)) if stamp is not None else None
    except (TypeError, ValueError, OverflowError, OSError): return None

def _read_response(response, deadline, maximum=1024 * 1024):
    """Read bounded bytes under one monotonic deadline, not per-recv time."""
    chunks=[]; size=0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0: return None
        # urllib's socket is deliberately implementation-private; where it is
        # exposed, reduce its per-recv timeout to the remaining global budget.
        try: response.fp.raw._sock.settimeout(remaining)
        except (AttributeError, OSError): pass
        part=response.read(min(65536, maximum + 1 - size))
        if not part: break
        size += len(part)
        if size > maximum: return None
        chunks.append(part)
    return b"".join(chunks)

def request_json(url, headers, params=None, opener=urlopen, timeout=10, deadline=None, failure=None):
    """Bounded TLS JSON GET; redirects and non-JSON provider errors fail closed."""
    if params: url += ("&" if "?" in url else "?") + urlencode(params)
    if deadline is not None and time.monotonic() >= deadline: return {}
    try:
        req=Request(url, headers=headers, method="GET")
        # Never follow a redirect: credentials must not be replayed to another
        # host (or even an unexpected route on this fixed provider endpoint).
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, msg, headers, newurl): return None
        open_fn = opener if opener is not urlopen else build_opener(NoRedirect()).open
        remaining = timeout if deadline is None else deadline - time.monotonic()
        if remaining <= 0: return {}
        with open_fn(req, timeout=min(timeout, remaining)) as response:
            read_deadline = time.monotonic() + min(timeout, remaining)
            data=_read_response(response, read_deadline)
            if data is None: return {}
        return json.loads(data.decode("utf-8"))
    except HTTPError as exc:
        if isinstance(failure, dict): failure["retry_after"] = _retry_after(exc.headers.get("Retry-After") if exc.headers else None)
        return {}
    except (URLError, OSError, ValueError): return {}

def request_pages(url, headers, params=None, opener=urlopen, limit=20, timeout=20, failure=None):
    """Follow provider-issued page tokens only, with a finite request budget."""
    out=[]; page=None; seen=set(); deadline=time.monotonic() + timeout
    for _ in range(limit):
        if time.monotonic() >= deadline: return None
        query=dict(params or {})
        if page: query["page"] = page
        response=request_json(url, headers, query, opener, deadline=deadline, failure=failure)
        if not isinstance(response, dict) or response == {} or not isinstance(response.get("data"), list) or not isinstance(response.get("has_more"), bool): return None
        out.extend(response["data"])
        if not response["has_more"]: return out
        page=response.get("next_page")
        if not isinstance(page, str) or not page or page in seen: return None
        seen.add(page)
    return None  # page budget exhausted while the provider still said more

def anthropic_admin(start, end, opener=urlopen, failure=None):
    """Organization period rows, never session/turn billing."""
    key=os.environ.get("ANTHROPIC_ADMIN_KEY")
    if not key: return {}
    headers={"x-api-key":key, "anthropic-version":"2023-06-01"}
    def rfc(value):
        stamp=epoch(value)
        return datetime.fromtimestamp(stamp, timezone.utc).isoformat().replace("+00:00", "Z") if stamp is not None else None
    params={"starting_at":rfc(start), "ending_at":rfc(end)}
    if not params["starting_at"] or not params["ending_at"]: return {}
    deadline = time.monotonic() + 20
    usage=request_pages("https://api.anthropic.com/v1/organizations/usage_report/messages", headers, params, opener, timeout=max(.01, deadline-time.monotonic()), failure=failure)
    if usage is None or time.monotonic() >= deadline: return {}
    costs=request_pages("https://api.anthropic.com/v1/organizations/cost_report", headers, params, opener, timeout=max(.01, deadline-time.monotonic()), failure=failure)
    if usage is None or costs is None: return {}
    cents=0.0; inp=0; cached=0; output=0
    for item in costs:
        if not isinstance(item, dict) or not isinstance(item.get("results"), list): return {}
        for amount in item.get("results", []):
            if not isinstance(amount, dict): return {}
            value=_number(amount.get("amount"))
            if value is None or amount.get("currency") not in ("USD", "usd"): return {}
            cents += value
    for item in usage:
        if not isinstance(item, dict) or not isinstance(item.get("results"), list): return {}
        for result in item.get("results", []):
            if not isinstance(result, dict): return {}
            uncached=_number(result.get("uncached_input_tokens")); reads=_number(result.get("cache_read_input_tokens")); out=_number(result.get("output_tokens"))
            creates=result.get("cache_creation", {}) or {}
            if not isinstance(creates, dict) or None in (uncached, reads, out): return {}
            created=0
            for value in creates.values():
                n=_number(value)
                if n is None: return {}
                created += n
            inp += uncached + reads + created; cached += reads; output += out
    return normalise({"schema_version":1, "as_of":time.time(), "windows":[], "account":{"period_start":start, "period_end":end, "cost_usd":cents / 100.0, "input_tokens":inp, "cached_input_tokens":cached, "output_tokens":output, "scope":"organization"}}, "anthropic-admin")

def openai_admin(start, end, opener=urlopen, failure=None):
    key=os.environ.get("OPENAI_ADMIN_KEY")
    if not key: return {}
    headers={"Authorization":"Bearer " + key}
    params={"start_time":int(epoch(start) or 0), "end_time":int(epoch(end) or time.time()), "bucket_width":"1d"}
    deadline = time.monotonic() + 20
    completions=request_pages("https://api.openai.com/v1/organization/usage/completions", headers, params, opener, timeout=max(.01, deadline-time.monotonic()), failure=failure)
    if completions is None or time.monotonic() >= deadline: return {}
    costs=request_pages("https://api.openai.com/v1/organization/costs", headers, params, opener, timeout=max(.01, deadline-time.monotonic()), failure=failure)
    if completions is None or costs is None: return {}
    dollars=0.0; inp=0; cached=0; output=0
    for bucket in costs:
        if not isinstance(bucket, dict) or not isinstance(bucket.get("results"), list): return {}
        for result in bucket.get("results", []):
            if not isinstance(result, dict): return {}
            amount=result.get("amount", {})
            value=_number(amount.get("value")) if isinstance(amount, dict) else None
            if value is None or amount.get("currency") != "usd": return {}
            dollars += value
    for bucket in completions:
        if not isinstance(bucket, dict) or not isinstance(bucket.get("results"), list): return {}
        for result in bucket.get("results", []):
            if not isinstance(result, dict): return {}
            a=_number(result.get("input_tokens")); c=_number(result.get("input_cached_tokens")); o=_number(result.get("output_tokens"))
            if a is None or o is None or (c is not None and c > a): return {}
            inp += a; output += o
            # Unknown cache subset remains unknown across the whole period.
            if c is None: cached=None
            elif cached is not None: cached += c
    account={"period_start":start, "period_end":end, "cost_usd":dollars, "input_tokens":inp, "output_tokens":output, "scope":"organization"}
    if cached is not None: account["cached_input_tokens"]=cached
    return normalise({"schema_version":1, "as_of":time.time(), "windows":[], "account":account}, "openai-admin")

def experimental_claude_oauth(opener=urlopen, failure=None):
    token=os.environ.get("CLAUDE_OAUTH_ACCESS_TOKEN")
    if not token: return {}
    raw=request_json("https://api.anthropic.com/api/oauth/usage",
                     {"Authorization":"Bearer " + token, "anthropic-beta":"oauth-2025-04-20"}, opener=opener, failure=failure)
    if not raw: return {}
    windows=[]
    for name in ("five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet"):
        item=raw.get(name, {}) if isinstance(raw, dict) else {}
        if isinstance(item, dict) and item.get("utilization") is not None:
            duration=18000 if name == "five_hour" else 604800
            windows.append({"id":name, "duration_seconds":duration, "used_percent":item.get("utilization"), "resets_at":item.get("resets_at")})
    return normalise({"schema_version":1, "as_of":time.time(), "windows":windows}, "experimental-claude-oauth")

def experimental_codex_api(opener=urlopen, failure=None):
    token=os.environ.get("CODEX_USAGE_ACCESS_TOKEN")
    account=os.environ.get("CODEX_USAGE_ACCOUNT_ID")
    if not token or not account: return {}
    raw=request_json("https://chatgpt.com/backend-api/wham/usage",
                     {"Authorization":"Bearer " + token, "ChatGPT-Account-Id":account}, opener=opener, failure=failure)
    if not raw: return {}
    windows=[]
    values=[]
    if isinstance(raw, dict):
        rate=raw.get("rate_limit") or {}
        if isinstance(rate, dict):
            for kind in ("primary", "secondary"):
                window=rate.get(kind + "_window")
                if isinstance(window, dict):
                    window=dict(window); window["limit_id"]="codex:" + kind; window["bucket_id"]="codex"; window["heading"]="general"; values.append(window)
        for index, extra in enumerate(raw.get("additional_rate_limits") or []):
            if isinstance(extra, dict) and isinstance(extra.get("rate_limit"), dict):
                rate=extra["rate_limit"]
                label=_safe_text(extra.get("limit_name"), 128) or "additional"
                feature=_safe_text(extra.get("metered_feature"), 128)
                bucket_id=_safe_text(extra.get("limit_id"), 128) or feature or ("additional:%d" % index)
                for kind in ("primary", "secondary"):
                    window=rate.get(kind + "_window")
                    if isinstance(window, dict):
                        window=dict(window); window["limit_id"]="%s:%s" % (bucket_id, kind)
                        window["bucket_id"]=bucket_id
                        window["heading"]=label
                        window["feature"]=feature
                        values.append(window)
    for item in values:
        if not isinstance(item, dict): continue
        reset=item.get("reset_at")
        if reset is None and item.get("reset_after_seconds") is not None:
            delay=_number(item.get("reset_after_seconds"))
            reset=time.time()+delay if delay is not None else None
        windows.append({"id":str(item.get("limit_id") or item.get("id") or item.get("name") or "rate_limit"), "duration_seconds":item.get("limit_window_seconds"), "used_percent":item.get("used_percent"), "resets_at":reset,
                        "bucket_id": item.get("bucket_id"), "heading": item.get("heading"), "feature": item.get("feature")})
    return normalise({"schema_version":1, "as_of":time.time(), "windows":windows}, "experimental-codex-api")

def period_bounds(kind, now=None):
    now = datetime.now(timezone.utc) if now is None else datetime.fromtimestamp(now, timezone.utc)
    if kind == "day": start=now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif kind == "week": start=(now - __import__("datetime").timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif kind == "month": start=now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else: raise ValueError("account period must be day, week, or month")
    return start.timestamp(), now.timestamp()


def _cache_namespace(spec, account, context):
    """Avoid cache reuse after an implicit managed-account switch."""
    if account and account != "default": return str(account)
    context = context if isinstance(context, dict) else {}
    credentials = {"anthropic-admin": "ANTHROPIC_ADMIN_KEY", "openai-admin": "OPENAI_ADMIN_KEY",
                   "experimental-claude-oauth": "CLAUDE_OAUTH_ACCESS_TOKEN",
                   "experimental-codex-api": "CODEX_USAGE_ACCESS_TOKEN"}
    value = os.environ.get(credentials.get(spec, ""), "")
    if spec == "experimental-codex-api":
        value += "\0" + os.environ.get("CODEX_USAGE_ACCOUNT_ID", "")
    if value:
        return "credential:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    session = _safe_text(context.get("session"), 256)
    if session: return "session:" + session
    return "default"


def _native_windows(value):
    """Translate a transcript/native quota snapshot without inventing fields."""
    raw = value.get("rate_limits", value) if isinstance(value, dict) else {}
    windows = []
    if not isinstance(raw, dict): return windows
    source_bucket = str(raw.get("limit_id") or raw.get("limitId") or "default")
    aliases = (("five_hour", "five_hour"), ("seven_day", "seven_day"),
               ("primary", "primary"), ("secondary", "secondary"))
    for key, ident in aliases:
        item = raw.get(key)
        if not isinstance(item, dict): continue
        usage = item.get("used_percentage", item.get("used_percent"))
        if usage is None: continue
        duration = item.get("duration_seconds", item.get("limit_window_seconds", item.get("window_minutes")))
        if item.get("window_minutes") is not None and item.get("duration_seconds") is None and item.get("limit_window_seconds") is None:
            number = _number(duration); duration = number * 60 if number is not None else None
        if duration is None and key == "five_hour": duration = 5 * 3600
        if duration is None and key == "seven_day": duration = 7 * 86400
        windows.append({"id": ident,
                        "duration_seconds": duration, "used_percent": usage,
                        "resets_at": item.get("resets_at", item.get("reset_at")),
                        "bucket_id": str(item.get("bucket_id") or item.get("limit_id") or source_bucket),
                        "heading": str(item.get("heading") or source_bucket)})
    # Codex native rateLimit snapshots have primary/secondary windows nested.
    snapshots = []
    if isinstance(raw, dict):
        by_id = raw.get("rateLimitsByLimitId")
        if isinstance(by_id, dict):
            snapshots.extend((snapshot, key) for key, snapshot in by_id.items())
        for snapshot in (raw.get("rateLimits"), raw):
            if not isinstance(snapshot, dict): continue
            ident = snapshot.get("limitId")
            if isinstance(by_id, dict) and ident is not None and str(ident) in by_id:
                continue
            snapshots.append(snapshot)
    for snapshot in snapshots:
        map_key = None
        if isinstance(snapshot, tuple): snapshot, map_key = snapshot
        if not isinstance(snapshot, dict): continue
        for slot in ("primary", "secondary"):
            item = snapshot.get(slot)
            if isinstance(item, dict) and "usedPercent" in item:
                bucket_id = str(snapshot.get("limitId") or item.get("limitId") or map_key or "rate_limit")
                windows.append({"id": slot,
                                "duration_seconds": (_number(item.get("windowDurationMins")) or 0) * 60 or None,
                                "used_percent": item.get("usedPercent"), "resets_at": item.get("resetsAt"),
                                "bucket_id": bucket_id, "heading": str(snapshot.get("limitName") or bucket_id),
                                "model": snapshot.get("normalModelSlug"), "feature": snapshot.get("feature")})
    unique = []
    seen = set()
    for item in windows:
        key = (item.get("bucket_id"), item["id"], item.get("duration_seconds"), item.get("resets_at"))
        if key not in seen:
            seen.add(key); unique.append(item)
    return unique


def native_reading(agent, context):
    """Native readings are supplied by the active agent, never refreshed."""
    context = context if isinstance(context, dict) else {}
    source = "native"
    raw = context.get("rate_limits") or context.get("rateLimits") or context.get("quota") or {}
    windows = _native_windows(raw)
    if not windows: return {}
    return normalise({"schema_version": 1, "as_of": context.get("as_of"),
                      "windows": windows}, source)


def claude_usage_tracker():
    """Adapter for the known tracker schema without importing credentials."""
    try:
        from . import claude
        override = os.environ.get("CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST")
        if override:
            with open(os.path.expanduser(override), "rb") as fh: raw = claude.tracker_reading(plistlib.load(fh))
        else:
            source = claude.ClaudeUsageTrackerSource()
            if not source.available(): return {}
            raw = source.read()
        windows = []
        for ident, pct, reset, duration in (("five_hour", raw.get("session_pct"), raw.get("session_resets_at"), 18000),
                                            ("seven_day", raw.get("weekly_pct"), raw.get("weekly_resets_at"), 604800),
                                            ("seven_day_opus", raw.get("weekly_opus_pct"), raw.get("weekly_resets_at"), 604800)):
            if pct is not None: windows.append({"id": ident, "duration_seconds": duration, "used_percent": pct, "resets_at": reset})
        return normalise({"schema_version":1, "as_of":raw.get("as_of"), "windows":windows}, "claude-usage-tracker")
    except (OSError, ValueError, TypeError): return {}

def collect(agent, spec="auto", account="default", period="day", context=None, now=None):
    """Collect one selected reading with source/account/UTC-period isolation."""
    spec = validate_source(agent, spec)
    now = time.time() if now is None else now
    start, end = period_bounds(period, now)
    period_key = "%.0f" % start
    context = dict(context or {})
    context.update({"agent": agent, "account": account, "period": period,
                    "period_start": start, "period_end": end})
    namespace = _cache_namespace(spec, account, context)
    native = native_reading(agent, context)
    stale_native = {}
    raw_native_cache = state.load(agent, "native", namespace, period_key)
    cached_native = _cached_reading(raw_native_cache, "native", now, 60)
    current_native = _cached_reading(native, "native", now, 60) if native else {}
    # Native intake is local data, but a fresh normalized observation must be
    # available to a later Stop payload that contains no native quota block.
    # Stale input remains authoritative for this invocation only and may not
    # downgrade a newer cached observation.
    if current_native and not current_native.get("stale"):
        saved_native = _tag_identity(current_native, agent, "native", namespace, period_key)
        saved_native["fetched_at"] = now
        state.save(agent, "native", namespace, period_key, saved_native)
        cached_native = current_native = saved_native
    # Auto starts with active native data, then only its native cache; external
    # fallback is deliberately restricted to the local managed integrations.
    if spec == "native":
        # A supplied native snapshot is live input, not a cache candidate.
        # In particular do not mask it behind the previous fetch TTL.
        return _tag_identity(current_native if native else cached_native,
                             agent, "native", namespace, period_key)
    if spec == "auto" and native:
        if not current_native.get("stale"):
            return current_native
        stale_native = current_native
    if spec in ("none", "off"):
        cached_any = state.find_compatible(agent, namespace, period_key)
        source = "native" if native else cached_any.get("source", "")
        return _tag_identity((current_native if native else
                              _cached_reading(cached_any, source, now, 300)),
                             agent, source, namespace, period_key)
    selected = spec
    if spec == "auto":
        if cached_native and not cached_native.get("stale"): return cached_native
        selected = "codex-app-server" if agent == "codex" else "claude-usage-tracker"
    ttl = 300 if selected in ("anthropic-admin", "openai-admin", "experimental-claude-oauth", "experimental-codex-api") else 60
    raw_cache = state.load(agent, selected, namespace, period_key)
    cached = _cached_reading(raw_cache, selected, now, ttl)
    if not _refresh_due(raw_cache, now, ttl): return cached
    with state.refresh_lock(agent, selected, namespace, period_key) as acquired:
        if not acquired: return cached
        raw_cache = state.load(agent, selected, namespace, period_key)
        cached = _cached_reading(raw_cache, selected, now, ttl)
        if not _refresh_due(raw_cache, now, ttl): return cached
        failure = {}
        if selected.startswith("cmd:"): fresh = command_reading(selected[4:], context)
        elif selected == "native": fresh = native
        elif selected == "codex-app-server": fresh = codex_app_server()
        elif selected == "anthropic-admin": fresh = anthropic_admin(start, end, failure=failure)
        elif selected == "openai-admin": fresh = openai_admin(start, end, failure=failure)
        elif selected == "experimental-claude-oauth": fresh = experimental_claude_oauth(failure=failure)
        elif selected == "experimental-codex-api": fresh = experimental_codex_api(failure=failure)
        elif selected == "claude-usage-tracker": fresh = claude_usage_tracker()
        else: fresh = {}
        # All built-in/command collectors return the validated v1 form.  Do
        # not normalize it a second time: buckets are already canonical.
        fresh = fresh if fresh and isinstance(fresh, dict) and fresh.get("schema_version") == 1 else {}
        if fresh and has_reading(fresh):
            # A source as_of is evidence: never relabel a stale reading fresh.
            fresh["as_of"] = fresh.get("as_of") if fresh.get("as_of") is not None else now
            fresh = _cached_reading(fresh, selected, now, ttl)
            fresh.update({"agent": agent, "account_name": namespace, "period_start": period_key,
                          "fetched_at": now, "attempted_at": now, "fail_count": 0})
            state.save(agent, selected, namespace, period_key, fresh)
            return fresh
        failed = _failure_cache(raw_cache, now, ttl, failure.get("retry_after"))
        failed.update({"agent": agent, "account_name": namespace, "period_start": period_key})
        state.save(agent, selected, namespace, period_key, failed)
    return _tag_identity(cached or stale_native, agent,
                         selected if cached else "native", namespace, period_key)

def codex_app_server(executable="codex", timeout=5):
    """Read the one safe app-server endpoint with a byte-buffered deadline.

    Do not use ``TextIO.readline`` here: select can report a partial line and
    readline can then block past the operation deadline.  ``os.read`` lets us
    retain partial/burst JSON-RPC frames safely.
    """
    proc = None
    selector = None
    try:
        proc = subprocess.Popen([executable, "app-server", "--stdio"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + max(0.1, timeout)
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout.fileno(), selectors.EVENT_READ)
        pending = bytearray()

        def send(value):
            wire = (json.dumps(value, separators=(",", ":")) + "\n").encode("utf-8")
            proc.stdin.write(wire); proc.stdin.flush()

        def receive(ident):
            while time.monotonic() < deadline:
                cut = pending.find(b"\n")
                if cut >= 0:
                    line = bytes(pending[:cut]); del pending[:cut + 1]
                    if len(line) > 1024 * 1024: return {}
                    try: message = json.loads(line.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError): continue
                    if not isinstance(message, dict): continue
                    if message.get("id") == ident:
                        result = message.get("result")
                        return result if isinstance(result, dict) and "error" not in message else {}
                    continue
                ready = selector.select(max(0, deadline - time.monotonic()))
                if not ready: break
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk: break
                pending.extend(chunk)
                if len(pending) > 1024 * 1024: return {}
            return {}

        send({"jsonrpc":"2.0", "id":1, "method":"initialize",
              "params":{"clientInfo":{"name":"coding-agent-usage-line", "version":"1.0"}}})
        if not receive(1): return {}
        send({"jsonrpc":"2.0", "method":"initialized", "params":{}})
        send({"jsonrpc":"2.0", "id":2, "method":"account/rateLimits/read", "params":{}})
        result = receive(2)
        snapshots = []
        if isinstance(result, dict):
            canonical = result.get("rateLimits")
            by_id = result.get("rateLimitsByLimitId")
            if isinstance(by_id, dict):
                for key, snapshot in by_id.items():
                    # The keyed map is canonical and may carry more complete
                    # windows than the standalone snapshot.
                    if isinstance(snapshot, dict): snapshots.append((snapshot, str(key)))
            if isinstance(canonical, dict):
                canonical_id = _safe_text(canonical.get("limitId"))
                if not isinstance(by_id, dict) or canonical_id not in by_id:
                    snapshots.append((canonical, None))
        windows = []
        seen = set()
        for snapshot, map_key in snapshots:
            limit_id = _safe_text(snapshot.get("limitId")) or map_key or "rate_limit"
            limit_name = _safe_text(snapshot.get("limitName"), 128)
            for slot in ("primary", "secondary"):
                item = snapshot.get(slot)
                if not isinstance(item, dict): continue
                ident = "%s:%s" % (limit_id, slot)
                key = (ident, item.get("resetsAt"), item.get("windowDurationMins"))
                if key in seen: continue
                seen.add(key)
                windows.append({"id": slot,
                                "duration_seconds": (_number(item.get("windowDurationMins")) or 0) * 60 or None,
                                "used_percent": item.get("usedPercent"), "resets_at": item.get("resetsAt"),
                                "bucket_id": limit_id, "heading": limit_name or limit_id,
                                "model": snapshot.get("normalModelSlug"), "feature": snapshot.get("feature")})
        reading = normalise({"schema_version":1, "as_of":time.time(), "windows":windows}, "codex-app-server")
        return reading if has_reading(reading) else {}
    except (OSError, ValueError, TypeError):
        return {}
    finally:
        if selector:
            try: selector.close()
            except Exception: pass
        if proc is not None:
            try: proc.stdin.close()
            except (OSError, AttributeError): pass
            try: os.killpg(proc.pid, signal.SIGTERM)
            except (OSError, AttributeError):
                try: proc.terminate()
                except OSError: pass
            try: proc.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                try: os.killpg(proc.pid, signal.SIGKILL)
                except (OSError, AttributeError):
                    try: proc.kill()
                    except OSError: pass
                try: proc.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired): pass
