"""관광 서비스 브리프를 만드는 CLI.

# 파일 이름에 service_ 접두사를 붙인 이유: 다른 스킬에도 brief.py 가
# 있다. 한 프로세스에서 둘 다 쓰면 먼저 import 된 쪽이 sys.modules 를
# 차지해 다른 쪽을 조용히 대신 실행한다.
"""
import argparse
import pathlib
import sys

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (_SKILLS_ROOT / "datalab-fetch" / "scripts",
           _SKILLS_ROOT / "inbound-country-brief" / "scripts",
           _SKILLS_ROOT / "tourism-service-brief" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import period  # noqa: E402
import service_collect as collect  # noqa: E402
from service_render import render_report  # noqa: E402
import workspace  # noqa: E402

CACHE_DIR = workspace.cache_dir()
SESSION_FILE = workspace.session_file()
LOGIN_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "login.py")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="관광 불편신고·소비자 상담/위해·안내 문의·숙박 리뷰를 "
                    "한 장으로")
    parser.add_argument("--period", default="작년",
                        help="'작년'·'2024년'·'최근12개월' 같은 말도 된다")
    parser.add_argument("--from", dest="ym1")
    parser.add_argument("--to", dest="ym2")
    parser.add_argument("--out", help="HTML 경로. 없으면 표준출력")
    args = parser.parse_args(argv)

    if args.ym1 and args.ym2:
        ym1, ym2 = args.ym1, args.ym2
    else:
        try:
            ym1, ym2 = period.resolve(args.period)
        except period.PeriodError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    sections, meta = collect.collect(ym1, ym2, cache_dir=str(CACHE_DIR),
                                     session_file=str(SESSION_FILE))
    if not sections:
        if meta["세션상태"] == "만료":
            print(f"세션이 만료됐습니다. 다음을 실행하세요:\n  {LOGIN_HINT}",
                  file=sys.stderr)
            return 3
        print("수록된 지표가 없습니다. 기간을 넓혀 보세요.", file=sys.stderr)
        return 4

    html = render_report(sections, meta)
    if args.out:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        print(f"리포트를 만들었습니다: {out} "
              f"(수록 {meta['수록지표']}/{meta['시도지표']})")
    else:
        print(html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
