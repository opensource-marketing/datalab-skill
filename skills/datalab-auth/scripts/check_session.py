"""데이터랩 세션 상태를 진단한다.

세션 파일이 있어도 만료되었을 수 있다. 데이터랩은 인증 실패를 오류로
알려 주지 않으므로, 실제로 로그인해야 열리는 것을 한 번 열어 봐야 안다.

**지표(qid)로 판정하지 않는다.** 예전에는 인증이 필요하다고 알려진
지표를 호출해 값이 오는지로 판정했다. 그런데 데이터랩이 그 지표를
공개로 돌리자, 로그인하지 않은 세션도 값을 받아 늘 "유효"가 나왔다.
판정이 거짓말을 하기 시작한 것이다.

지금은 **로그인해야 내용이 붙는 화면**을 연다. 로그인 없이 열면 서버가
제목만 맞고 본문이 빠진 문서를 돌려준다(오류가 아니다). 화면 전용 JS가
붙어 있는지가 그 표시다.

혼자 보면 오판한다 — 사이트 개편이나 네트워크 문제로도 본문이 빠질 수
있기 때문이다. 그래서 **로그인 없이도 열리는 대조 화면**을 함께 연다.
대조 화면마저 비어 있으면 "로그인 안 됨"이 아니라 "알 수 없음"이다.
"""
import html as html_mod
import json
import pathlib
import re
import subprocess
import sys
import tempfile

BASE = "https://datalab.visitkorea.or.kr"
GO_URL = BASE + "/datalab/portal/goUrl.do"
MAIN_URL = BASE + "/datalab/portal/main/getMainForm.do"

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FETCH = _SKILLS_ROOT / "datalab-fetch" / "scripts"
if str(_FETCH) not in sys.path:
    sys.path.insert(0, str(_FETCH))

import workspace  # noqa: E402

STATE = workspace.session_file()
LOGIN_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "login.py")

# 로그인해야 본문이 붙는 화면. 익명으로 열면 화면 전용 JS가 0개다.
GATED_SCREEN = {"screen": "bda/getMetcoAna",
                "menu_cd": "10401010000002021100613",
                "name": "빅데이터 > 이동통신 > 지역별 방문자수"}

# 로그인 없이도 본문이 붙는 화면. 이것까지 비면 로그인 문제가 아니다.
CONTROL_SCREEN = {"screen": "loc/getAreaDataForm",
                  "menu_cd": "10102030000002020091512",
                  "name": "지역별 분석 > 지역별 현황 > 지역별 관광 현황"}

# 화면 전용 JS. /js/portal/<영역>/<파일>.js 만 화면 것이고
# /js/portal/*.js 와 /js/portal/lib/* 는 공용이다.
_PAGE_JS = re.compile(r'src="/js/portal/(?!lib/)[a-z]+/[^"?]+\.js')
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)

# 로그인 쿠키의 이름은 사이트 사정이라 언제든 바뀐다. 예전에는 `key`
# 하나만 보고 판정했는데, 이름이 바뀌자 멀쩡히 로그인한 사용자에게도
# "로그인 쿠키 없음"이 나왔다. 그래서 이 목록은 **참고용 표시**일 뿐이고,
# 유효성의 근거는 언제나 아래의 실호출(probe)이다.
KNOWN_LOGIN_COOKIES = ("key", "loginKey", "LOGIN_KEY")

# 로그인과 무관한 쿠키. 이것뿐이면 아직 로그인 전이다.
ANONYMOUS_COOKIES = ("KSESSIONID", "JSESSIONID", "WMONID")


def _cookie_header(session_file):
    state = json.loads(pathlib.Path(session_file).read_text())
    return "; ".join(f'{c["name"]}={c["value"]}'
                     for c in state.get("cookies", []))


def has_login_cookie(names):
    """쿠키 이름만 보고 "로그인한 것 같은가"를 어림한다.

    **유효성의 근거가 아니다.** 아는 이름이 있으면 그것으로, 없으면
    익명 쿠키 말고 다른 것이 하나라도 있는지로 어림한다. 이름 목록을
    고정해 두면 사이트가 쿠키 이름을 바꾸는 날 모든 사용자가 "쿠키
    없음"으로 보이기 때문이다. 진짜 판정은 probe가 한다.
    """
    names = {n for n in names if n}
    if names & set(KNOWN_LOGIN_COOKIES):
        return True
    return bool(names - set(ANONYMOUS_COOKIES))


def _open_screen(screen, menu_cd, cookie):
    """메뉴를 눌러 들어가듯 화면을 연다. 본문 HTML 또는 None.

    주소로 바로 열면 어느 화면이든 본문이 비어 있다. 서버가 메뉴를
    거쳐 온 요청에만 본문을 붙이기 때문이다. 그래서 사이트가 하는 그대로
    goUrl.do 에 폼을 보낸다 — 브라우저 없이 curl로 재현할 수 있다.

    **세션 쿠키가 있어야 한다.** 사이트 세션 쿠키(KSESSIONID) 없이
    goUrl.do 를 부르면 서버가 요청한 화면 대신 첫 화면을 돌려준다.
    첫 화면에도 JS가 있어서, 세션 없이 판정하면 "본문이 왔다"로
    잘못 읽는다.

    그래서 쿠키를 받았으면 그것만 쓰고, 못 받았을 때만 첫 화면을 한 번
    받아 새 세션을 만든다. **둘을 섞지 않는 것이 중요하다** — 자루가
    만든 익명 세션과 넘겨받은 로그인 세션을 함께 보내면 서버가 어느
    쪽을 볼지 알 수 없고, 그러면 멀쩡히 로그인한 사람이 "로그인 안 됨"으로
    판정될 수 있다.
    """
    base = ["curl", "-s", "--max-time", "40", "-H", "User-Agent: Mozilla/5.0"]
    open_cmd = ["-L", GO_URL, "-H", f"Referer: {MAIN_URL}",
                "--data-urlencode", f"userMenuUrl=/datalab/portal/{screen}.do",
                "--data-urlencode", f"currMenu={menu_cd}",
                "--data-urlencode", "menuDepth=3"]
    try:
        if cookie:
            proc = subprocess.run(base + ["-H", "Cookie: " + cookie] + open_cmd,
                                  capture_output=True, text=True)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                jar = str(pathlib.Path(tmp) / "cookies.txt")
                jarred = base + ["-c", jar, "-b", jar]
                seed = subprocess.run(jarred + ["-o", "/dev/null", MAIN_URL],
                                      capture_output=True, text=True)
                if seed.returncode != 0:
                    return None
                proc = subprocess.run(jarred + open_cmd,
                                      capture_output=True, text=True)
    except OSError:
        # curl 실행 자체가 안 되는 환경 문제. 세션과 무관하다.
        return None
    if proc.returncode != 0:
        # 네트워크 단절, DNS 실패, 타임아웃 등. 세션 만료와 구분해야 한다.
        return None
    return proc.stdout


def _title(html):
    match = _TITLE.search(html or "")
    return html_mod.unescape(match.group(1)).strip() if match else ""


def on_screen(html, leaf):
    """요청한 화면에 실제로 닿았는지. 제목 끝이 그 메뉴 이름이어야 한다.

    서버는 화면을 못 열어 줄 때 오류가 아니라 첫 화면을 돌려준다.
    제목을 보지 않으면 그 첫 화면을 "본문이 온 것"으로 읽는다.
    """
    return _title(html).endswith(leaf)


def has_content(html):
    """본문이 붙은 문서인지. 화면 전용 JS가 있으면 붙은 것이다."""
    return bool(html) and bool(_PAGE_JS.search(html))


def _leaf(spec):
    return spec["name"].split(">")[-1].strip()


def _control_opens_without_cookie():
    """쿠키 없이 대조 화면이 열리는가.

    열린다면 사이트도 네트워크도 멀쩡하다는 뜻이다. 그러면 같은 요청이
    쿠키와 함께 실패한 이유는 하나뿐이다 — 그 쿠키가 무효다.
    """
    html = _open_screen(CONTROL_SCREEN["screen"],
                        CONTROL_SCREEN["menu_cd"], "")
    return (html is not None
            and on_screen(html, _leaf(CONTROL_SCREEN))
            and has_content(html))


def probe_login(cookie):
    """이 쿠키가 로그인된 세션인지 판정한다.

    True  로그인됨 (막힌 화면의 본문이 붙어 왔다)
    False 로그인 안 됨 (막힌 화면은 비었는데 대조 화면은 붙어 왔다)
    None  알 수 없음 (화면에 닿지도 못했거나 대조 화면마저 비었다)

    None을 False로 뭉개지 않는 것이 이 함수의 요점이다. 네트워크가
    끊긴 것을 "로그인이 풀렸다"고 말하면 사용자는 멀쩡한 세션을 지우고
    다시 로그인한다.
    """
    gated = _open_screen(GATED_SCREEN["screen"], GATED_SCREEN["menu_cd"], cookie)
    if gated is None or not on_screen(gated, _leaf(GATED_SCREEN)):
        # 화면에 닿지 못했다. 두 가지가 섞여 있다 — 사이트·네트워크
        # 문제이거나, **그 쿠키를 보냈기 때문에** 서버가 첫 화면으로
        # 되돌린 것이거나. 쿠키를 빼고 한 번 더 열어 보면 갈린다.
        # 빼면 열린다는 것은 사이트가 아니라 그 쿠키가 무효라는 뜻이다.
        if cookie and _control_opens_without_cookie():
            return False
        return None
    if has_content(gated):
        return True

    control = _open_screen(CONTROL_SCREEN["screen"],
                           CONTROL_SCREEN["menu_cd"], cookie)
    if (control is None or not on_screen(control, _leaf(CONTROL_SCREEN))
            or not has_content(control)):
        # 로그인 없이도 열리는 화면까지 비었다. 여기서도 쿠키를 빼고
        # 확인한다 — 빼면 열리면 사이트가 아니라 그 쿠키가 문제다.
        if cookie and _control_opens_without_cookie():
            return False
        return None
    return False


def describe(session_file, probe=True):
    """세션 상태를 진단해 dict로 반환한다.

    "유효" 필드는 세 가지 상태를 가진다:
    - True: 로그인해야 열리는 화면의 본문이 붙어 왔다. 세션이 살아 있다.
    - False: 그 화면은 비었는데 대조 화면은 붙어 왔다(또는 파일이 손상됨).
      세션이 만료됐거나 무효하다.
    - None: 유효한지 알 수 없다. probe=False로 확인 자체를 안 했거나(상태:
      "미확인"), probe는 했지만 호출 실패·사이트 개편으로 판단할 수 없었다
      (상태: "확인불가"). 이 두 경우를 "만료"로 뭉뚱그리면 사용자에게
      거짓 정보를 주게 되므로 반드시 "상태" 필드로 구분해 알려준다.

    모든 반환 경로는 동일한 키 집합
    ("존재", "쿠키수", "로그인쿠키", "유효", "상태", "메시지")을 갖는다.
    """
    path = pathlib.Path(session_file)
    if not path.exists():
        return {"존재": False, "쿠키수": 0, "로그인쿠키": False, "유효": None,
                "상태": "미확인",
                "메시지": f"세션 파일이 없습니다. 다음을 실행하세요:\n  {LOGIN_HINT}"}

    try:
        state = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"존재": True, "쿠키수": 0, "로그인쿠키": False, "유효": False,
                "상태": "만료",
                "메시지": f"세션 파일이 손상되었습니다. 다시 만드세요:\n  {LOGIN_HINT}"}

    cookies = state.get("cookies", [])
    names = {c.get("name") for c in cookies}
    has_login = has_login_cookie(names)
    result = {"존재": True, "쿠키수": len(cookies), "로그인쿠키": has_login,
              "유효": None, "상태": "미확인", "메시지": ""}

    if not probe:
        result["메시지"] = ("세션 파일이 있습니다. 유효성은 확인하지 않았습니다."
                          if has_login else
                          f"로그인 쿠키가 없습니다. 다시 로그인하세요:\n  {LOGIN_HINT}")
        return result

    verdict = probe_login(_cookie_header(path))

    if verdict is None:
        # 호출이 실패했거나, 로그인 없이도 열리는 대조 화면까지 비었다.
        # 세션 문제인지 네트워크·사이트 문제인지 구분할 수 없으므로
        # 재로그인을 안내하지 않는다.
        result["유효"] = None
        result["상태"] = "확인불가"
        result["메시지"] = (
            "세션 유효성을 확인할 수 없습니다. 로그인 없이도 열리는 대조 "
            f"화면({CONTROL_SCREEN['name']})까지 본문이 오지 않았습니다. "
            "네트워크·프록시 상태를 확인한 뒤 다시 시도하세요. 그래도 같다면 "
            "데이터랩이 화면 구조를 바꾼 것일 수 있습니다. "
            "이 결과만으로는 재로그인이 필요한지 알 수 없습니다.")
        return result

    result["유효"] = verdict
    result["상태"] = "유효" if verdict else "만료"
    result["메시지"] = (
        f"세션이 유효합니다. 로그인해야 열리는 화면"
        f"({GATED_SCREEN['name']})이 열렸습니다."
        if verdict else
        f"세션이 만료되었습니다. 다음을 실행해 갱신하세요:\n  {LOGIN_HINT}")
    return result


USAGE = """사용법: python3 check_session.py [--no-probe]

저장된 데이터랩 세션이 살아 있는지 확인합니다.
  --no-probe   서버에 물어보지 않고 파일과 쿠키만 봅니다(네트워크 없음).

종료 코드: 0 = 유효하거나 로그인 쿠키가 있음, 1 = 만료이거나 쿠키 없음"""


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if any(a in ("-h", "--help") for a in argv):
        print(USAGE)
        return 0
    probe = "--no-probe" not in argv
    out = describe(STATE, probe=probe)
    print(f"세션 파일 : {STATE}")
    print(f"존재      : {'예' if out['존재'] else '아니오'}")
    print(f"쿠키 수   : {out['쿠키수']}")
    print(f"로그인쿠키: {'있음' if out['로그인쿠키'] else '없음'}")
    print(f"상태      : {out['상태']}")
    print()
    print(out["메시지"])

    if out["유효"] is True:
        return 0
    if out["유효"] is False:
        return 1
    # 유효 여부를 알 수 없는 경우(미확인 또는 확인불가). "모른다"를
    # "만료"로 뭉개지 않고, 우리가 실제로 아는 정보인 로그인 쿠키의
    # 존재 여부로 종료 코드를 정한다.
    return 0 if out["로그인쿠키"] else 1


if __name__ == "__main__":
    sys.exit(main())
