"""데이터랩 로그인 세션을 만든다.

**로그인은 대부분의 경우 필요 없다.** 데이터랩 지표는 거의 다 공개다
(로그인 없이 실호출 37가지가 모두 통과한다). 이 스크립트는 로그인해야
열리는 몇몇 화면을 쓸 때만 필요하다.

하는 일은 셋뿐이다.

  1. 브라우저 창을 연다
  2. 사용자가 로그인하고 창을 닫는다
  3. 닫히기 직전의 쿠키를 파일로 저장한다

**로그인됐는지 우리가 알아내려 하지 않는다.** 예전에는 쿠키 이름을
보거나, 인증 지표를 호출해 보거나, 막힌 화면을 열어 보는 식으로 자동
판정을 했다. 셋 다 한 번씩 틀렸고, 틀릴 때마다 사용자는 멀쩡히 로그인해
놓고 "감지되지 않았습니다"를 봐야 했다. 사람에게 물어보는 편이 짧고
정확하다.

인출은 이 브라우저가 하지 않는다. 실제 데이터는 curl이 이 파일의 쿠키를
들고 가서 받아온다. 그래서 창을 닫아도 세션은 남는다.
"""
import json
import pathlib
import sys

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 자기 디렉토리(check_session)와 datalab-fetch(workspace)를 함께 넣는다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (pathlib.Path(__file__).resolve().parent,
           _SKILLS_ROOT / "datalab-fetch" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import check_session  # noqa: E402
import workspace  # noqa: E402

BASE = "https://datalab.visitkorea.or.kr"
MAIN_URL = BASE + "/datalab/portal/main/getMainForm.do"
LOGIN_URL = BASE + "/datalab/portal/mbr/getMbrLoginForm.do"
STATE = workspace.session_file()
# 로그인을 기억해 두는 브라우저 프로필. 다음 실행 때 다시 로그인하지
# 않아도 되게 한다. workspace.auth_dir() 밑이라 작업 공간(기본
# .datalab/, .gitignore 대상)과 함께 커밋에서 빠진다.
PROFILE_DIR = workspace.auth_dir() / "browser"
# 무슨 일이 있었는지 남기는 곳. 로그인이 안 될 때 되짚기 위한 것이다.
LOG_PATH = workspace.auth_dir() / "login-debug.log"

# 자동화로 열었다는 표시를 지운다. 그 표시를 보고 로그인을 거절하는
# 사이트가 있다. 사용자가 자기 계정으로 자기 브라우저에 로그인하는
# 일이므로 감출 것이 따로 있는 게 아니다.
_STEALTH_ARGS = ["--disable-blink-features=AutomationControlled"]

# 로그인을 마쳤다는 신호로 **창 닫기**를 쓴다.
#
# 터미널에서 Enter를 받는 방법을 먼저 썼는데, Claude Code에서 `!`로
# 실행하면 표준입력이 대화형이 아니라 그 자리에서 EOF가 난다. 사용자는
# 브라우저를 보고 있는데 스크립트는 이미 끝나 버린다.
#
# 창을 닫는 것은 어디서 실행하든 똑같이 되고, 사용자가 이미 브라우저를
# 보고 있으므로 손이 가 있는 곳에서 끝난다.
WAIT_LIMIT_SEC = 900
_SNAPSHOT_SEC = 2


def _cookie_header(cookies):
    return "; ".join(f'{c["name"]}={c["value"]}' for c in cookies)


def logged_in(cookies):
    """이 쿠키가 로그인된 세션인지. True / False / None(알 수 없음).

    저장한 **뒤에 알려 주기만 하는** 용도다. 이것으로 저장 여부를 정하지
    않는다 — 판정이 틀려도 사용자의 로그인을 버리지 않기 위해서다.
    """
    return check_session.probe_login(_cookie_header(cookies))


def _launch(play):
    """브라우저를 연다. 실제 Chrome을 먼저 시도하고 없으면 Chromium."""
    common = {"user_data_dir": str(PROFILE_DIR), "headless": False,
              "viewport": {"width": 1440, "height": 900},
              "args": _STEALTH_ARGS}
    try:
        return play.chromium.launch_persistent_context(channel="chrome", **common)
    except PlaywrightError:
        return play.chromium.launch_persistent_context(**common)


LOGIN_API = "/datalab/portal/mbr/login.do"
_notes = []


def _note(text):
    """화면에 적고 동시에 남긴다. 로그인 실패는 되짚어 볼 수 있어야 한다."""
    print(text, flush=True)
    _notes.append(text)


def _write_notes():
    """무슨 일이 있었는지 파일로 남긴다. 실패해도 로그인 결과를 뒤엎지 않는다."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text("\n".join(_notes) + "\n", encoding="utf-8")
    except OSError:
        pass


def _show_dialogs(page):
    """사이트가 하는 말을 사용자에게 그대로 전한다.

    **알림창.** playwright는 dialog 핸들러가 없으면 alert를 조용히 닫아
    버린다. 데이터랩은 로그인 실패 이유를 alert로 알려 주므로, 핸들러가
    없으면 "왜 안 되는지"가 통째로 사라진다.

    **로그인 응답.** 데이터랩은 결과를 rtnCd로 알려 준다. 이것을 읽어
    두면 로그인이 된 것인지 추측하지 않아도 된다. 아이디·비밀번호는
    요청 쪽에 있고 우리는 응답의 코드와 안내문만 본다.
    """
    def on_dialog(dialog):
        _note(f"  [사이트 알림] {dialog.message}")
        dialog.accept()

    def on_response(response):
        """로그인 응답의 **머리말**만 읽는다.

        가로채서(route) 본문까지 읽어 본 적이 있는데, 그러면 요청이
        브라우저 바깥에서 나가 서버가 새로 내준 세션 쿠키가 브라우저에
        붙지 않는다. 로그인은 성공(rtnCd=S)했는데 브라우저는 여전히
        로그아웃인 일이 그래서 난다.

        머리말은 화면이 이동해도 남아 있으므로 본문 없이도 읽을 수 있다.
        Set-Cookie가 있는지가 특히 중요하다 — 서버가 로그인 때 세션을
        새로 발급하는지 알려 준다.
        """
        if LOGIN_API not in response.url:
            return
        _note(f"  [로그인 응답] HTTP {response.status}")
        headers = response.all_headers()
        if "set-cookie" in headers:
            names = [part.split("=", 1)[0].strip()
                     for part in headers["set-cookie"].split("\n")]
            _note(f"  [로그인 응답] 새 쿠키를 내줌: {', '.join(names)}")
        if headers.get("location"):
            _note(f"  [로그인 응답] 넘김: {headers['location'][:120]}")

    def on_request(request):
        if LOGIN_API in request.url:
            _note("  [로그인 시도] 요청을 보냈습니다")

    page.on("dialog", on_dialog)
    page.on("request", on_request)
    page.on("response", on_response)


def _open_login(page):
    """첫 화면을 거쳐 로그인 화면으로 들어간다.

    **로그인 주소로 바로 가면 안 된다.** 데이터랩의 로그인 성공 처리가
    이렇게 돼 있기 때문이다:

        document.FrmSearch.action = document.referrer;
        document.FrmSearch.submit();

    주소창으로 바로 들어오면 document.referrer가 빈 문자열이라, 로그인에
    성공한 뒤 폼이 **현재 주소(로그인 화면)로 제출된다.** 그래서 로그인을
    했는데 로그인 화면이 다시 나오고, 사용자는 실패한 줄 안다.
    """
    page.goto(MAIN_URL, wait_until="domcontentloaded")
    try:
        page.evaluate("() => funLogInDataLab()")
        page.wait_for_load_state("domcontentloaded")
    except PlaywrightError:
        # 사이트가 그 함수를 없앴다면 주소로라도 연다.
        page.goto(LOGIN_URL, wait_until="domcontentloaded")


def _browser_says_logged_in(page):
    """브라우저가 지금 로그인 상태로 보이는지.

    사이트가 화면에 심어 두는 loginYn을 읽는다. 우리가 밖에서 쿠키로
    찔러 보는 것보다 확실하다 — 브라우저는 그 세션의 당사자다.
    데이터랩 화면이 아니면 판단하지 않는다(빈 문자열이 나온다).
    """
    try:
        value = page.evaluate(
            """() => {
                const m = document.documentElement.innerHTML
                    .match(/var loginYn = "([^"]*)"/);
                return m ? m[1] : "";
            }""")
    except PlaywrightError:
        return False
    return bool(value)


def _wait_for_close(ctx):
    """창이 닫힐 때까지 기다렸다가, 닫히기 직전의 쿠키를 돌려준다.

    쿠키를 미리 찍어 두는 것이 요점이다. 창이 닫힌 뒤에는 ctx.cookies()가
    함께 죽어서 아무것도 못 가져온다. 2초마다 찍어 두면 닫는 순간과
    차이가 없다 — 그 사이에 로그인이 새로 일어나지는 않는다.
    """
    snapshot = ctx.cookies()
    waited = 0
    seen_logged_in = False
    while waited < WAIT_LIMIT_SEC:
        try:
            if not ctx.pages:
                break
            page = ctx.pages[0]
            page.wait_for_timeout(_SNAPSHOT_SEC * 1000)
            snapshot = ctx.cookies()
            if not seen_logged_in and _browser_says_logged_in(page):
                # 브라우저 안에서 본 로그인 상태가 가장 확실한 근거다.
                # 이 순간의 쿠키가 우리가 원하는 것이다.
                seen_logged_in = True
                _note("  [확인] 브라우저가 로그인 상태가 되었습니다. "
                      "창을 닫으면 이 세션을 저장합니다.")
        except PlaywrightError:
            # 기다리는 도중에 닫혔다. 마지막으로 찍어 둔 것을 쓴다.
            break
        waited += _SNAPSHOT_SEC
    else:
        print(f"{WAIT_LIMIT_SEC // 60}분이 지나 그만 기다립니다. "
              "지금 상태로 저장합니다.", file=sys.stderr)
    return snapshot


def _save(cookies):
    """쿠키를 세션 파일로 남긴다."""
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"cookies": cookies, "origins": []},
                                ensure_ascii=False))


USAGE = """사용법: python3 login.py

데이터랩 로그인 창을 띄웁니다. 로그인을 마치고 창을 닫으면
그 세션을 저장합니다: {state}

아이디와 비밀번호는 브라우저에만 입력되며 이 스크립트가 읽지 않습니다.

대부분의 지표는 로그인 없이도 나옵니다. 로그인은 일부 화면에만 필요합니다.
Claude Code 안에서는 앞에 `!`를 붙여 실행하세요."""


def main(argv=None):
    try:
        return _main(argv)
    finally:
        _write_notes()


def _main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if any(a in ("-h", "--help") for a in argv):
        # 도움말을 물었는데 브라우저가 열리면 놀란다. 창을 띄우기 전에 막는다.
        print(USAGE.format(state=STATE))
        return 0

    with sync_playwright() as play:
        try:
            ctx = _launch(play)
        except PlaywrightError as exc:
            print("브라우저를 실행하지 못했습니다. 다음을 먼저 실행하세요:\n"
                  "  python3 -m playwright install chromium\n"
                  f"원인: {exc}", file=sys.stderr)
            return 1

        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            _show_dialogs(page)
            _open_login(page)
            print("브라우저에서 데이터랩에 로그인해 주세요.\n"
                  "로그인이 끝나면 **브라우저 창을 닫으세요.** 그 순간의 "
                  "세션을 저장합니다.", flush=True)
            cookies = _wait_for_close(ctx)
            if not any("[로그인 시도]" in n for n in _notes):
                _note("  [알림] 로그인 요청이 한 번도 나가지 않았습니다. "
                      "브라우저에서 로그인 버튼을 누르지 않았거나, "
                      "창을 먼저 닫은 것입니다.")
        except KeyboardInterrupt:
            print("\n그만둡니다. 저장하지 않았습니다.", file=sys.stderr)
            return 1
        finally:
            try:
                ctx.close()
            except PlaywrightError:
                pass

    _save(cookies)
    print(f"세션을 저장했습니다: {STATE}")

    verdict = logged_in(cookies)
    if verdict is True:
        print("로그인된 세션입니다.")
        return 0
    if verdict is False:
        print("확인해 보니 로그인되지 않은 세션입니다. 브라우저에서 로그인이 "
              "끝난 것을 보고 창을 닫았는지 확인하고 다시 실행해 주세요.",
              file=sys.stderr)
        return 1
    print("로그인 여부는 확인하지 못했습니다(네트워크 또는 사이트 변경). "
          "세션은 저장했으니 그대로 써 보셔도 됩니다.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
