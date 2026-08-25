"""고부가 관광 테마 브리프를 생성하는 CLI.

# 파일 이름에 theme_ 접두사를 붙인 이유: inbound-country-brief도 brief.py를
# 가지고 있다. 한 파이썬 프로세스에서 둘 다 쓰면 먼저 import된 쪽이
# sys.modules를 차지해 다른 쪽을 조용히 대신 실행한다.
"""
import argparse
import pathlib
import re
import sys

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (_SKILLS_ROOT / "datalab-fetch" / "scripts",
           _SKILLS_ROOT / "inbound-country-brief" / "scripts",
           _SKILLS_ROOT / "theme-market-brief" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import client
import period
import theme_collect as collect
import theme_config as config
from theme_render import render_report
import workspace  # noqa: E402

CACHE_DIR = workspace.cache_dir()
SESSION_FILE = workspace.session_file()
PERIOD = re.compile(r"^\d{4}(\d{2})?$")
LOGIN_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "login.py")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="고부가 관광 테마 브리프를 만든다")
    parser.add_argument("--theme", required=True, metavar="테마",
                        # 손으로 적어 두면 테마가 늘어도 도움말은 그대로
                        # 남는다. 실제로 크루즈가 빠진 채 오래 있었다.
                        help=" / ".join(config.THEMES) + " "
                             "(의료관광·마이스처럼 풀어 써도 됩니다)")
    parser.add_argument("--out", required=True, metavar="FILE")
    parser.add_argument("--sido", default=None,
                        help="야간관광에만 쓴다. 시도명 또는 두 자리 코드")
    parser.add_argument("--country", default=None,
                        help="한류에만 쓴다. 한글 국가명(기본 글로벌)")
    period.add_arguments(parser)
    args = parser.parse_args(argv)

    try:
        args.theme = config.resolve_theme(args.theme)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # 연 단위 테마(한류)에 --period 를 월로 풀어 넣으면 오류가 아니라
    # 빈 배열이 온다. 기본 기간의 글자 수로 되짚지 않고 선언을 읽는다 —
    # MICE 는 기본 기간이 월 여섯 자리지만 값은 연 단위로 온다.
    year_theme = config.THEMES[args.theme].get("period") == "year"
    if args.period:
        try:
            args.ym1, args.ym2 = period.resolve(args.period)
        except period.PeriodError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if year_theme:
            args.ym1, args.ym2 = args.ym1[:4], args.ym2[:4]
    else:
        for label, value in (("--from", args.ym1), ("--to", args.ym2)):
            if value is not None and not PERIOD.match(value):
                print(f"{label} 은 YYYYMM 또는 YYYY 형식이어야 합니다: {value}",
                      file=sys.stderr)
                return 1
        if (args.ym1 is None) != (args.ym2 is None):
            print("--from 과 --to 는 함께 주거나 함께 비워야 합니다. "
                  "한쪽만 알면 --period 를 쓰세요 (예: --period 작년)",
                  file=sys.stderr)
            return 1
        if args.ym1 and args.ym1 > args.ym2:
            print("--from 이 --to 보다 뒤일 수 없습니다.", file=sys.stderr)
            return 1
    if args.sido and args.country:
        print("--sido 와 --country 를 함께 쓸 수 없습니다. 테마가 받는 축은 "
              "하나입니다.", file=sys.stderr)
        return 1

    axis_value = args.sido or args.country
    try:
        sections, meta = collect.collect(
            args.theme, axis_value=axis_value, ym1=args.ym1, ym2=args.ym2,
            cache_dir=str(CACHE_DIR), session_file=str(SESSION_FILE))
    except collect.CollectError as exc:
        print(exc, file=sys.stderr)
        return 2
    except client.SessionExpired:
        print(f"세션이 만료됐습니다. 다음을 실행하세요:\n  {LOGIN_HINT}",
              file=sys.stderr)
        return 3

    if meta["수록지표"] == 0:
        if meta["세션상태"] == "만료":
            print(f"세션이 만료되어 지표를 하나도 가져오지 못했습니다.\n"
                  f"  {LOGIN_HINT}", file=sys.stderr)
            return 3
        print(f"지표를 하나도 가져오지 못했습니다. 기간을 확인하세요. "
              f"{config.THEMES[args.theme]['label']}의 기본 기간은 "
              f"{'~'.join(config.default_period(args.theme))}입니다.",
              file=sys.stderr)
        return 4

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(sections, meta), encoding="utf-8")
    print(f"리포트를 생성했습니다: {out} "
          f"(수록 {meta['수록지표']}/{meta['시도지표']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
