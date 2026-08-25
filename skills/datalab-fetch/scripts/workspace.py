"""캐시와 세션이 놓이는 자리를 여기서만 정한다.

**스킬이 설치된 곳과 사용자가 일하는 곳은 다르다.** 예전에는 저장소
루트 하나가 둘 다였다 — 소스 트리 안에 스킬도 있고 캐시도 있어서
우연히 같았을 뿐이다. 배포하면 스킬은 사용자가 고른 임의의 위치에 놓이는데,
거기에 storage_state.json(로그인 세션)이 생기면 스킬 디렉토리를 git
으로 관리하는 사람이 세션을 그대로 커밋한다.

그래서 작업 공간은 **명령을 실행한 곳** 기준이다. 형제 프로젝트
using-google-analytics 가 .ga4/ 를 같은 방식으로 쓴다 — 둘을 같이
쓰는 사람이 규칙 두 개를 외우지 않아도 되게 맞췄다.

모듈 상수가 아니라 함수인 이유는 import 시점이 아니라 호출 시점의
cwd 를 봐야 하기 때문이다. 상수로 두면 cwd 를 바꾼 뒤에도 옛 경로를
준다.
"""
import os
import pathlib

# 사용자가 옮기고 싶을 때 쓰는 환경변수. 캐시가 11MB 넘게 자란다.
ENV_VAR = "DATALAB_HOME"
DEFAULT_DIRNAME = ".datalab"


def root() -> pathlib.Path:
    """작업 공간 루트. 없으면 현재 디렉토리의 .datalab/.

    상대 경로로 와도 절대 경로로 푼다 — 인출 계층이 curl 서브프로세스를
    쓰는데, 상대 경로를 그대로 넘기면 프로세스마다 다른 디렉토리를
    캐시로 본다.
    """
    override = os.environ.get(ENV_VAR)
    if override:
        return pathlib.Path(override).resolve()
    return (pathlib.Path.cwd() / DEFAULT_DIRNAME).resolve()


def cache_dir() -> pathlib.Path:
    """인출 캐시. 지워도 다시 만들어진다."""
    return root() / "data" / "raw"


def auth_dir() -> pathlib.Path:
    """로그인 산출물이 모이는 곳. 절대 커밋되면 안 된다."""
    return root() / ".auth"


def session_file() -> pathlib.Path:
    """세션 쿠키. 이 파일 하나면 계정이 통째로 넘어간다."""
    return auth_dir() / "storage_state.json"


def display_path(skills_root: pathlib.Path, skill: str, script: str) -> str:
    """사용자에게 보여 줄 스크립트 경로.

    LOGIN_HINT 같은 문자열 상수는 {SKILLS_DIR} 을 쓸 수 없다 — 에이전트가
    아니라 사람이 읽고 그대로 붙여 넣기 때문이다. 그래서 실제 경로를
    만들되, 명령은 보통 프로젝트 루트에서 실행하므로 cwd 하위면 상대
    경로로 짧게 보여 준다.
    """
    p = skills_root / skill / "scripts" / script
    try:
        return str(p.relative_to(pathlib.Path.cwd()))
    except ValueError:
        return str(p)
