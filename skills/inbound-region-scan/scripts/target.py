"""특정 국가 관광객을 겨냥한 지역 후보를 찾는 CLI."""
import argparse
import pathlib
import sys
import time

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (_SKILLS_ROOT / "datalab-fetch" / "scripts",
           _SKILLS_ROOT / "inbound-country-brief" / "scripts",
           _SKILLS_ROOT / "inbound-region-scan" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import target_collect as collect
import codes
import period
from target_render import render_report
import workspace  # noqa: E402

CACHE_DIR = workspace.cache_dir()
SESSION_FILE = workspace.session_file()
MAX_MONTHS = 18
SORT_COLUMNS = ("방문자수", "국적_비중", "카드소비", "1인당_소비")
SAMPLE_REGION = "11110"   # 국적 목록을 물어볼 기준 지역(서울 종로구)
LOGIN_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "login.py")


def _month_span(ym1, ym2):
    y1, m1 = int(ym1[:4]), int(ym1[4:])
    y2, m2 = int(ym2[:4]), int(ym2[4:])
    return (y2 - y1) * 12 + (m2 - m1) + 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="특정 국가 관광객을 겨냥한 지역 후보를 찾는다")
    parser.add_argument("--country", required=True,
                        help="국가 이름. 일본인·USA·타이완처럼 써도 된다")
    period.add_arguments(parser)
    parser.add_argument("--out", required=True, metavar="FILE")
    parser.add_argument("--sido", default=None,
                        help="한 시도로 좁힌다. 없으면 전국 271곳을 훑는다(20분쯤)")
    parser.add_argument("--sort", default="방문자수", choices=SORT_COLUMNS)
    parser.add_argument("--top", type=int, default=20,
                        help="표에 보일 지역 수. 0이면 전부")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        args.ym1, args.ym2 = period.from_args(args, max_months=MAX_MONTHS)
    except period.PeriodError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    def progress(done, total, name):
        if not args.quiet:
            print(f"\r  {done}/{total} {name}          ", end="",
                  file=sys.stderr)

    # 이 스킬은 응답의 국적 이름을 직접 비교하므로 codes.resolve_country
    # 를 거치지 않는다. 사람이 쓰는 "일본인 관광객"을 여기서도 풀어 준다.
    args.country = codes.nationality_name(args.country)

    started = time.monotonic()
    try:
        frame, meta = collect.collect(
            args.country, sido=args.sido, ym1=args.ym1, ym2=args.ym2,
            cache_dir=str(CACHE_DIR), session_file=str(SESSION_FILE),
            progress=progress)
    except collect.CollectError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2
    if not args.quiet:
        print(f"\r  {time.monotonic() - started:.0f}초 걸렸습니다.{' ' * 30}",
              file=sys.stderr)

    if frame.empty:
        if meta["세션상태"] == "만료":
            print(f"세션이 만료됐습니다. 다음을 실행하세요:\n  {LOGIN_HINT}",
                  file=sys.stderr)
            return 3
        # 국적 이름을 의심하기 전에 기간부터 짚는다. 아직 발표되지 않은
        # 달을 물었다면 어떤 국적을 넣어도 빈 결과가 온다.
        gap = period.explain_gap(collect.QID_NATIONALITY, args.ym1, args.ym2)
        if gap:
            print(gap, file=sys.stderr)
            return 4
        known = collect.known_countries(
            SAMPLE_REGION, args.ym1, args.ym2, cache_dir=str(CACHE_DIR),
            session_file=str(SESSION_FILE))
        print(f"'{args.country}' 국적이 어느 지역 응답에도 없습니다.",
              file=sys.stderr)
        if known:
            print(f"쓸 수 있는 국적 이름: {', '.join(known)}", file=sys.stderr)
        return 4

    frame = frame.sort_values(args.sort, ascending=False, na_position="last",
                              kind="mergesort").reset_index(drop=True)
    frame.insert(0, "순위", range(1, len(frame) + 1))

    # 상위 세 곳만 곁다리로 본다. 271곳을 다시 훑으면 몇 분이 더 든다.
    languages = []
    for _, row in frame.head(3).iterrows():
        code = codes.resolve_region(row["지역"])[0][0]
        rows, reason = collect.language_interest(
            args.country, code, args.ym1, args.ym2,
            cache_dir=str(CACHE_DIR), session_file=str(SESSION_FILE))
        languages.append((row["지역"], rows, reason))

    html = render_report(frame, meta, sort_column=args.sort,
                         limit=None if args.top == 0 else args.top,
                         languages=languages)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"리포트를 생성했습니다: {out} "
          f"(값이 나온 지역 {meta['값있는지역수']}/{meta['훑은지역수']}곳)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
