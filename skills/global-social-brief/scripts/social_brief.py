"""해외 소셜미디어 브리프 CLI.

    python3 social_brief.py --period 최근12개월 --country 일본 --out /tmp/s.html
"""
import argparse
import pathlib
import sys

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (_SKILLS_ROOT / "datalab-fetch" / "scripts",
           _SKILLS_ROOT / "global-social-brief" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import period  # noqa: E402
import social_collect as collect  # noqa: E402
import social_config as config  # noqa: E402
import social_render as render  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="해외에서 한국 관광을 어떻게 이야기하는지 한 장으로")
    parser.add_argument("--period", default="최근12개월",
                        help="작년 · 2025년 · 최근12개월 같은 말도 된다")
    parser.add_argument("--from", dest="ym1", help="시작 연월(YYYYMM)")
    parser.add_argument("--to", dest="ym2", help="끝 연월(YYYYMM)")
    parser.add_argument("--country", default=config.DEFAULT_COUNTRY,
                        help=f"국가별 표를 만들 나라 (기본 {config.DEFAULT_COUNTRY})")
    parser.add_argument("--out", help="HTML 경로. 없으면 표준출력")
    args = parser.parse_args(argv)

    if args.ym1 and args.ym2:
        ym1, ym2 = args.ym1, args.ym2
    else:
        try:
            ym1, ym2 = period.resolve(args.period)
        except period.PeriodError as exc:
            print(exc)
            return 2

    sections, meta = collect.collect(ym1, ym2, country=args.country)
    if meta["세션상태"] == "만료":
        print("세션이 만료되었습니다. datalab-auth 스킬로 갱신하세요.")
        return 3
    if not sections:
        print("수록된 지표가 0개입니다. 기간을 넓혀 보세요.")
        return 4

    html = render.render_report(sections, meta)
    if args.out:
        path = pathlib.Path(args.out)
        path.write_text(html, encoding="utf-8")
        print(f"리포트를 만들었습니다: {path} "
              f"(수록 {meta['수록지표']}/{meta['시도지표']})")
    else:
        print(html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
