"""처음 쓰는 사람이 막히는 곳을 한 번에 짚어 준다.

설치·네트워크·로그인·데이터 표까지 순서대로 보고, **지금 해야 할 일 한
가지**를 마지막에 알려 준다. 여러 개를 늘어놓지 않는다 — 초보자에게
필요한 것은 목록이 아니라 다음 한 걸음이다.
"""
import argparse
import importlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import unicodedata

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FETCH = _SKILLS_ROOT / "datalab-fetch" / "scripts"
if str(_FETCH) not in sys.path:
    sys.path.insert(0, str(_FETCH))

import workspace  # noqa: E402

SESSION_FILE = workspace.session_file()
COVERAGE_PATH = _SKILLS_ROOT / "datalab-fetch" / "catalog" / "coverage.yaml"
CACHE_DIR = workspace.cache_dir()
ENDPOINT = "https://datalab.visitkorea.or.kr/visualize/getTempleteData.do"

OK, WARN, BAD = "정상", "주의", "막힘"
# 없어도 되는 것. 경고로 띄우면 "해결해야 쓸 수 있다"로 읽힌다.
SKIP = "선택"

# 스킬을 쓰는 데 꼭 있어야 하는 패키지. 없으면 막힘이다.
REQUIRED_PACKAGES = [
    ("pandas", "pandas", "pandas>=2.0"),
    ("yaml", "PyYAML", "PyYAML>=6.0"),
]
# 테스트 스위트를 돌릴 때만 필요하다. README 의 설치 안내에도 없다 —
# 없다고 BAD 로 띄우면 방금 설치만 한 사용자를 막는다. 게다가 배포본에는
# requirements.txt 자체가 없어서(release.sh 가 복사하지 않는다) 그
# 파일을 가리키는 안내는 배포본에서 막다른 길이다.
OPTIONAL_PACKAGES = [
    ("pytest", "pytest", "pytest>=7.4"),
]


def _python():
    version = sys.version_info
    text = f"Python {version.major}.{version.minor}.{version.micro}"
    if version < (3, 9):
        return BAD, text + " — 3.9 이상이 필요합니다", "python3 --version 을 확인하세요"
    return OK, text, None


def _missing(packages):
    missing = []
    for module, _package, spec in packages:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(spec)
    return missing


def _packages():
    missing_required = _missing(REQUIRED_PACKAGES)
    if missing_required:
        return (BAD, f"빠진 패키지: {', '.join(missing_required)}",
                "pip install " + " ".join(f'"{spec}"' for spec in missing_required))
    missing_optional = _missing(OPTIONAL_PACKAGES)
    if missing_optional:
        return (SKIP,
                f"빠진 패키지: {', '.join(missing_optional)} — 테스트 스위트를 돌릴 때만 필요합니다",
                "pip install " + " ".join(f'"{spec}"' for spec in missing_optional))
    return OK, "pandas · PyYAML · pytest 모두 있음", None


def _curl():
    path = shutil.which("curl")
    if not path:
        return BAD, "curl 이 없습니다", "curl 을 설치하세요 (macOS 는 기본 포함)"
    return OK, path, None


def _network():
    """로그인 없이도 값이 나오는 지표를 하나 불러 본다."""
    cmd = ["curl", "-s", "--max-time", "30", ENDPOINT,
           "-H", "X-Requested-With: XMLHttpRequest",
           "-H", "User-Agent: Mozilla/5.0",
           "--data-urlencode", "qid=LN_04_01_022",
           "--data-urlencode", "SGG_CD=51150",
           "--data-urlencode", "BASE_YM1=202401",
           "--data-urlencode", "BASE_YM2=202403",
           "--data-urlencode", "srchAreaDate=1",
           "--data-urlencode", "tabDiv=1",
           "--data-urlencode", "dispYn=Y"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        return BAD, f"curl 실행 실패: {exc}", "네트워크·프록시 설정을 확인하세요"
    if proc.returncode != 0:
        return (BAD, f"curl 실패 (rc={proc.returncode})",
                "사내 프록시나 방화벽이 datalab.visitkorea.or.kr 을 막고 있는지 "
                "확인하세요")
    try:
        rows = json.loads(proc.stdout).get("list", [])
    except json.JSONDecodeError:
        return (BAD, "응답이 JSON이 아닙니다 — 프록시가 가로챘을 수 있습니다",
                "네트워크·프록시 설정을 확인하세요")
    if not rows:
        return (WARN, "연결은 되지만 값이 비어 있습니다",
                "잠시 뒤 다시 실행해 보세요")
    return OK, f"공개 지표에서 {len(rows)}건 받음", None


def _playwright():
    """로그인 창을 띄울 수 있는지. **없어도 된다.**

    브라우저가 깔려 있는지까지 확인하지는 않는다. 확인하려면 playwright
    드라이버를 띄워야 하는데, 그 과정이 진단 화면 맨 위에 예외 덩어리를
    토해 내서 "뭔가 고장 났다"처럼 보인다. 브라우저가 없으면 login.py가
    실행되는 순간 무엇을 설치해야 하는지 알려 주므로, 여기서 미리 겁을
    줄 이유가 없다.
    """
    try:
        importlib.import_module("playwright")
    except ImportError:
        # 인출은 curl이 한다. playwright는 로그인 창을 띄울 때만 쓰고,
        # 로그인은 일부 화면에만 필요하다.
        return (SKIP, "playwright 없음 — 로그인이 필요할 때만 설치하면 됩니다",
                "python3 -m playwright install chromium")
    return OK, "playwright 있음 (로그인 창용)", None


def _session(probe=True):
    # 부를 때마다 경로가 쌓이지 않게 한 번만 넣는다.
    auth_scripts = str(_SKILLS_ROOT / "datalab-auth" / "scripts")
    if auth_scripts not in sys.path:
        sys.path.insert(0, auth_scripts)
    import check_session
    out = check_session.describe(SESSION_FILE, probe=probe)
    login = "python3 " + workspace.display_path(
        _SKILLS_ROOT, "datalab-auth", "login.py")
    if out["상태"] == "유효":
        return OK, "로그인 세션 유효", None
    if not probe:
        # 서버에 물어보지 않기로 했으므로 만료 여부를 알 수 없다. 모르는
        # 것을 "다시 로그인하라"로 말하면 멀쩡한 세션을 버리게 만든다.
        return ((OK, "세션 파일 있음 (유효성은 확인하지 않음)", None)
                if out["로그인쿠키"] else
                (WARN, "세션 파일이 없거나 로그인 쿠키가 없습니다", login))
    # 로그인은 선택이다. 실호출 37가지가 로그인 없이 모두 통과한다.
    # 경고로 띄우면 "이걸 해결해야 쓸 수 있다"로 읽힌다.
    return (SKIP,
            f"{out['상태']} — 대부분의 지표는 로그인 없이 나옵니다",
            login)


def _coverage():
    if not COVERAGE_PATH.exists():
        # 이 표를 채우는 도구는 카탈로그를 관리하는 개발 전용이라
        # 배포본에는 없다 — 배포본은 표가 이미 채워진 채로 나간다.
        # 그런데도 없다면 안내할 수 있는 것은 스킬 설치 자체를
        # 다시 확인하라는 것뿐이다.
        return (WARN, "지표별 수록 시점 표가 없습니다",
                f"{COVERAGE_PATH} 파일이 없습니다. datalab-fetch 스킬을 "
                "다시 설치하세요. (이 표를 채우는 도구는 소스 저장소에만 "
                "있습니다)")
    import yaml
    table = yaml.safe_load(COVERAGE_PATH.read_text()) or {}
    known = sum(1 for r in table.values() if r.get("latest"))
    dates = {r.get("확인일") for r in table.values() if r.get("확인일")}
    when = max(dates) if dates else "?"
    return OK, f"{known}/{len(table)}개 지표의 수록 시점을 알고 있음 ({when} 확인)", None


def _cache():
    """인출 캐시가 얼마나 쌓였는지 알린다.

    캐시가 없는 것은 문제가 아니다. 처음 쓰는 사람이 경고를 보고 뭔가
    잘못됐다고 생각하면 안 된다. 그런데도 보여 주는 이유는, 값이 있는데
    이상할 때 **의심할 자리를 알려 주기 위해서**다 — 데이터랩이 지난달
    값을 정정해도 캐시된 옛 값이 계속 나온다. 존재를 모르면 의심할 수도
    없다.
    """
    if not CACHE_DIR.exists():
        return OK, "아직 없음 (첫 조회 때 만들어집니다)", None
    files = [f for f in CACHE_DIR.glob("*.json") if f.is_file()]
    if not files:
        return OK, "비어 있음", None
    size = sum(f.stat().st_size for f in files)
    return (OK,
            f"{len(files)}개 · {size / 1024 / 1024:.1f}MB "
            f"(값이 이상하면 지우고 다시: rm -rf {CACHE_DIR})",
            None)


CHECKS = [
    ("파이썬", _python),
    ("패키지", _packages),
    ("curl", _curl),
    ("데이터랩 연결", _network),
    ("브라우저(로그인용)", _playwright),
    ("로그인 세션", _session),
    ("지표 수록 시점 표", _coverage),
    ("인출 캐시", _cache),
]

MARK = {OK: "✓", WARN: "△", BAD: "✗", SKIP: "·"}


def _width(text):
    """한글은 터미널에서 두 칸을 쓴다. 칸 수를 세어야 표가 맞는다."""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1
               for ch in text)


def _pad(text, width):
    return text + " " * max(0, width - _width(text))


def run(checks=None, *, probe=True):
    """모든 항목을 검사해 [(이름, 상태, 설명, 고치는_명령)] 을 돌려준다."""
    results = []
    for name, check in (checks or CHECKS):
        if check is _session:
            state, detail, fix = check(probe=probe)
        else:
            state, detail, fix = check()
        results.append((name, state, detail, fix))
    return results


def next_step(results):
    """지금 해야 할 일 한 가지. 다 괜찮으면 None."""
    for _, state, _, fix in results:
        if state == BAD and fix:
            return fix
    for _, state, _, fix in results:
        if state == WARN and fix:
            return fix
    return None


USAGE = """사용법: python3 doctor.py [--no-network]

한국관광 데이터랩 스킬을 쓸 준비가 되었는지 순서대로 확인합니다.
  --no-network  서버에 물어보지 않고 설치 상태만 봅니다."""


SKILL_MD = pathlib.Path(__file__).resolve().parents[1] / "SKILL.md"
EXAMPLE_HEADING = "## 5. 그대로 물어봐도 되는 예시"


def 예시질문(limit=8, path=None):
    """안내 스킬의 예시 절에서 읽어 온다.

    **여기에 따로 적어 두면 두 곳이 갈린다.** 새 스킬을 만들고 안내에만
    적으면 처음 온 사용자는 그런 것을 물을 수 있다는 사실을 모르고,
    반대로 여기에만 적으면 시키는 대로 물었는데 받을 스킬이 없다.
    한 곳에서 읽어 그 어긋남 자체를 없앤다.

    파일을 못 읽으면 빈 목록을 준다 — 진단 도구가 목록 하나 때문에
    죽으면 안 된다.
    """
    try:
        글 = (path or SKILL_MD).read_text(encoding="utf-8")
    except OSError:
        return []
    if EXAMPLE_HEADING not in 글:
        return []
    뒤 = 글.split(EXAMPLE_HEADING, 1)[1].split("\n## ", 1)[0]
    return re.findall(r'^- "([^"]+)"', 뒤, re.M)[:limit]


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        print(USAGE)
        return 0

    checks = CHECKS
    if args.no_network:
        checks = [(n, c) for n, c in CHECKS if c not in (_network,)]

    # 작업 공간을 ~/.datalab이 아니라 ./.datalab로 둔 대가는 실수로
    # 커밋될 위험이다. README의 .gitignore 안내만으로는 부족하다 —
    # 사용자가 지금 어디를 보고 있는지 알아야 그 위험을 스스로 판단한다.
    print(f"작업 공간: {workspace.root()}")
    print()

    results = run(checks, probe=not args.no_network)
    width = max(_width(name) for name, *_ in results)
    for name, state, detail, _ in results:
        print(f"{MARK[state]} {_pad(name, width)}  {detail}")

    step = next_step(results)
    print()
    if step is None:
        print("준비가 끝났습니다. 이렇게 물어보세요:")
        for 말 in 예시질문():
            print(f'  "{말}"')
        return 0
    print("다음에 할 일:")
    print(f"  {step}")
    return 1 if any(s == BAD for _, s, _, _ in results) else 0


if __name__ == "__main__":
    sys.exit(main())
