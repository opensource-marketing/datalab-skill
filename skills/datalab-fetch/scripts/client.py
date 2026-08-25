"""한국관광 데이터랩 단일 데이터 API 클라이언트.

이 환경에는 SSL 인터셉트 프록시가 있어 Python의 TLS 검증이 실패한다.
따라서 HTTP 호출은 requests가 아니라 curl 서브프로세스로 한다.
"""
import hashlib
import json
import pathlib
import subprocess
import time

import workspace

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다. 사용자에게
# 보여 줄 로그인 힌트를 만드는 데만 쓴다 — workspace.py 가 이미 같은
# 디렉토리에 있으므로 소비 스킬을 import하는 것은 아니다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
_LOGIN_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "login.py")

BASE = "https://datalab.visitkorea.or.kr"
ENDPOINT = BASE + "/visualize/getTempleteData.do"
# 데이터랩의 두 번째 데이터 API. 피벗 그리드로 그리는 화면(세계관광통계
# 등)만 이쪽을 쓴다. 응답 모양은 같고(list) 주소만 다르다.
GRID_ENDPOINT = BASE + "/visualize/getGridData.do"
REFERER = BASE + "/datalab/portal/nat/getForTourForm.do"
RATE_LIMIT_SEC = 0.5
_last_call = 0.0

# 세션 판정용 기준 국가. 외래관광객조사(NAT_07_01_018 등)는 조사 대상국이
# 약 20개국뿐이라 대부분의 국가에서 빈 배열이 "세션 만료"가 아니라
# "이 나라는 조사 대상이 아님"을 뜻한다. 중국은 외래관광객조사가 항상
# 포함하는 국가이므로, 원래 조회가 빈 배열일 때 세션이 실제로 유효한지
# 판별하는 기준(프로브)으로 쓴다. 절대 다른 국가로 "단순화"하지 말 것 —
# 조사 커버리지가 없는 국가를 기준으로 쓰면 프로브 자체가 오판한다.
_PROBE_NAT_CD = "CN"
_PROBE_NAT_NM = "중국"

# 프로브 판정 결과의 캐시. None=아직 프로브 안 함.
# 209개국을 순회해도 프로브는 최대 한 번만 실행되어야 하므로 캐시한다.
# 다만 "유효함(True)" 판정만 _PROBE_TTL_SEC 뒤에 만료시킨다. 장기 실행
# 프로세스(반복되는 Q&A 호출 등)에서 세션이 중간에 끊기면, True를 영구히
# 캐시할 경우 그 뒤의 모든 국가가 "조사 대상이 아님"으로 조용히 오분류되기
# 때문이다. "만료함(False)" 판정은 만료시키지 않는다 — 이미 그 즉시
# SessionExpired를 던지므로 다시 확인해도 다시 False가 될 뿐이고, 같은
# 실행 안에서 세션이 스스로 되살아날 일은 없다.
_PROBE_TTL_SEC = 600  # 10분
_session_probe_ok = None
_session_probe_checked_at = None


class SessionExpired(Exception):
    """인증이 필요한 qid가 빈 배열을 반환했을 때."""


class FetchError(Exception):
    """curl 실패 또는 JSON 파싱 실패."""


class EmptyBody(FetchError):
    """응답 본문이 아예 비어 있다.

    파라미터가 모자라면 데이터랩은 빈 배열도 오류 코드도 아닌 **0바이트
    본문**을 준다. 네트워크·프록시 실패와 구분해야 하는 이유는, 전자는
    "이 지표를 그 조건으로는 부를 수 없다"이고 후자는 "지금 아무것도
    부를 수 없다"이기 때문이다. 둘을 섞어 잡으면 프록시가 죽은 채로
    돌린 결과를 "그 지표는 원래 안 된다"로 기록하게 된다.
    """



def load_cookie_header(session_file):
    """Playwright storage_state JSON을 Cookie 헤더 문자열로 변환한다."""
    path = pathlib.Path(session_file)
    if not path.exists():
        return ""
    state = json.loads(path.read_text())
    return "; ".join(f'{c["name"]}={c["value"]}' for c in state.get("cookies", []))


def _curl_post(url, fields, cookie):
    """curl로 form POST를 보내고 응답 본문을 문자열로 반환한다."""
    cmd = ["curl", "-s", "--fail-with-body", "--max-time", "60", url,
           "-H", "X-Requested-With: XMLHttpRequest",
           "-H", "Referer: " + REFERER,
           "-H", "User-Agent: Mozilla/5.0"]
    if cookie:
        cmd += ["-H", "Cookie: " + cookie]
    for k, v in fields.items():
        cmd += ["--data-urlencode", f"{k}={v}"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FetchError(f"curl 실패(rc={proc.returncode}): {proc.stdout[:200]}")
    return proc.stdout


def _cache_path(cache_dir, qid, fields, auth):
    # auth 등급(public/session)이 다르면 응답 의미가 달라지므로 해시 대상에 포함한다.
    # 그렇지 않으면 public으로 캐시된 빈 배열이 session 조회를 가로채
    # SessionExpired 판정을 은폐할 수 있다.
    payload = {"fields": fields, "auth": auth}
    digest = hashlib.sha1(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:12]
    return pathlib.Path(cache_dir) / f"{qid}_{digest}.json"


def _call_api(fields, cookie, endpoint=None):
    """레이트리밋을 지키며 curl로 실제 호출하고 list를 반환한다."""
    global _last_call
    elapsed = time.monotonic() - _last_call
    if elapsed < RATE_LIMIT_SEC:
        time.sleep(RATE_LIMIT_SEC - elapsed)
    body = _curl_post(endpoint or ENDPOINT, fields, cookie)
    _last_call = time.monotonic()

    if not body.strip():
        raise EmptyBody("응답 본문이 비어 있다(파라미터가 모자란 듯하다)")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise FetchError(f"JSON 파싱 실패. 응답 앞부분: {body[:200]}") from exc

    return payload.get("list", [])


def _probe_session_valid(qid, fields, cookie):
    """중국(CN) 기준 프로브로 세션이 실제로 유효한지 판정하고 캐시한다.

    외래관광객조사류 qid는 중국을 반드시 포함하므로, 같은 qid를 중국으로
    다시 호출했을 때 값이 나오면 세션은 유효한 것이고 원래의 빈 배열은
    "그 나라는 조사 대상이 아님"을 뜻한다. 중국 프로브마저 비어 있으면
    세션이 실제로 만료된 것이다.
    """
    global _session_probe_ok, _session_probe_checked_at
    now = time.monotonic()
    if _session_probe_ok is True:
        if (_session_probe_checked_at is not None
                and now - _session_probe_checked_at < _PROBE_TTL_SEC):
            return True
        # True 캐시가 만료됐다 — 다시 확인한다(아래로 흘러 재프로브).
    elif _session_probe_ok is False:
        return False

    probe_fields = dict(fields)
    probe_fields["natCd"] = _PROBE_NAT_CD
    if "natNm" in probe_fields:
        probe_fields["natNm"] = _PROBE_NAT_NM

    probe_rows = _call_api(probe_fields, cookie)
    _session_probe_ok = bool(probe_rows)
    _session_probe_checked_at = now
    return _session_probe_ok



def _통합시_재시도(fields, cookie, endpoint):
    """통합시 모시 코드가 빈 배열을 받았을 때 `sggIntgYnFlag='Y'` 로 한 번 더.

    수원시 같은 통합시는 시 전체 코드(41110)와 구 코드(41111…)로
    나뉘어 산다. 그런데 **어느 쪽으로 값을 주느냐를 가르는 것이
    `sggIntgYnFlag` 였다.** 카탈로그의 서른아홉 지표가 이 값을 "N"
    으로 못 박고 있었고, 그래서 수원시를 시 코드로 물으면 열여섯
    지표가 통째로 빈 배열이었다 — 읍면동 성·연령 열둘이 전부 그랬다.

        SGG_CD=41110 · N → 0행      SGG_CD=41110 · Y → 12행
        SGG_CD=41111 · N → 12행     SGG_CD=41111 · Y → 0행

    **"Y 가 낫다"가 아니다.** 같은 플래그를 쓰는 지표 중 셋은 N 이
    더 많은 행을 준다(51 → 31). 그래서 늘 Y 를 보내지 않고, N 이
    빈손으로 돌아왔을 때만, 그것도 통합시 모시 코드일 때만 다시
    부른다. 호출 하나가 더 드는 자리는 통합시 열셋뿐이다.
    """
    if fields.get("sggIntgYnFlag") != "N":
        return []
    code = str(fields.get("SGG_CD") or "")
    if not code:
        return []
    import codes  # 지연 import — codes 가 client 를 부르지 않아 순환은 없지만,
                  # 인출 계층이 코드 표 로딩 비용을 늘 치를 이유는 없다.
    if not codes.children(code):
        return []
    try:
        return _call_api({**fields, "sggIntgYnFlag": "Y"}, cookie, endpoint)
    except (FetchError, EmptyBody):
        # **보조 호출의 실패가 본 호출의 결과를 덮으면 안 된다.**
        # 첫 호출은 이미 성공해 빈 배열을 받았다. 그 뜻은 "그 조건으로는
        # 값이 없다"이고, 리포트는 그것을 "데이터없음"으로 적으면 된다.
        # 여기서 예외를 올리면 없어도 그만인 두 번째 호출 때문에
        # (프록시가 순간 끊기거나 60초를 넘기면) 리포트가 통째로 죽는다.
        return []


def fetch(qid, params, *, auth="public", cache_dir=None, session_file=None,
          endpoint=None):
    """qid와 파라미터로 데이터랩 API를 호출해 레코드 리스트를 반환한다.

    auth="session"인 qid가 빈 배열을 반환하면 곧바로 SessionExpired를
    던지지 않는다. 외래관광객조사는 약 20개국만 다루므로, 조사 대상이
    아닌 국가는 세션이 멀쩡해도 빈 배열이 온다. 그래서 중국(CN) 기준
    프로브로 세션이 실제로 유효한지 먼저 확인한 뒤 판단한다.
    """
    global _last_call, _session_probe_ok
    fields = dict(params)
    fields["qid"] = qid
    fields.setdefault("srchAreaDate", "1")

    cached = None
    if cache_dir is not None:
        cached = _cache_path(cache_dir, qid, fields, auth)
        cached.parent.mkdir(parents=True, exist_ok=True)
        if cached.exists():
            try:
                return json.loads(cached.read_text())["list"]
            except (json.JSONDecodeError, KeyError):
                # 캐시 파일이 잘렸거나 형식이 어긋났다. 지우지 않고
                # 캐시 미스로 취급해 아래 정상 인출 경로로 흘려보낸다 —
                # 인출에 성공하면 끝에서 이 파일을 다시 써서 자연히 복구된다.
                pass

    cookie = load_cookie_header(session_file) if session_file else ""

    rows = _call_api(fields, cookie, endpoint)

    if not rows:
        rows = _통합시_재시도(fields, cookie, endpoint)

    if not rows and auth == "session":
        if fields.get("natCd") == _PROBE_NAT_CD:
            # 이 요청 자체가 이미 중국(프로브 기준국)을 조회한 것이다.
            # 이게 비었다는 것 자체가 곧 세션 만료의 증거이므로, 프로브를
            # 재귀적으로 다시 돌리지 않고 바로 만료 처리한다.
            _session_probe_ok = False
            raise SessionExpired(
                f"{qid}는 로그인 세션이 필요합니다. 다음을 실행해 세션을 갱신하세요:\n"
                f"  {_LOGIN_HINT}"
            )
        if not _probe_session_valid(qid, fields, cookie):
            raise SessionExpired(
                f"{qid}는 로그인 세션이 필요합니다. 다음을 실행해 세션을 갱신하세요:\n"
                f"  {_LOGIN_HINT}"
            )
        # 프로브 결과 세션은 유효하다 → 원래의 빈 배열은 해당 국가에
        # 조사 데이터가 없다는 뜻이므로 그대로 빈 리스트를 반환한다.

    # 빈 배열은 캐시하지 않는다. 데이터랩에서 빈 배열은 "값이 없다"가
    # 아니라 "아직 발표되지 않았다" 또는 "파라미터가 틀렸다"일 때가
    # 많고, 둘 다 시간이 지나거나 다시 부르면 달라진다. 그것을 파일로
    # 굳혀 두면 데이터가 나온 뒤에도 계속 없다고 답하게 된다.
    #
    # 값을 치른다. rank.py 의 전국 271회 훑기에서 값이 없는 지역은 다시
    # 돌릴 때마다 또 부른다(0.5초 × N). 레이트리밋을 우회하지 않기로 한
    # 이상 이쪽이 느려지는 것을 택했다 — 틀린 답을 빠르게 주는 것보다
    # 맞는 답을 느리게 주는 편이 낫다. 빈 결과만 짧은 TTL로 따로
    # 캐시하는 절충은 아직 하지 않았다.
    if cached is not None and rows:
        cached.write_text(json.dumps({"list": rows}, ensure_ascii=False))
    return rows
