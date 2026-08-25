"""전국 관광 현황 브리프 CLI.

인자 검증 · 종료 코드 · 파일 쓰기만 한다. 인출은 national_collect가,
HTML은 national_render가 맡는다.
"""
import argparse
import pathlib
import sys

# HERE 의 parents[1] 이 skills 루트다(자기 자신은 <skills 루트>/<이름>/scripts).
HERE = pathlib.Path(__file__).resolve().parent
_SKILLS_ROOT = HERE.parents[1]
for _p in (HERE, _SKILLS_ROOT / "datalab-fetch" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import national_collect as collect  # noqa: E402
import national_render as render  # noqa: E402
import period  # noqa: E402

AGES = ("20", "30", "40", "50", "60")


def build(ym1, ym2, *, cache_dir=None, age=None):
    data, meta = collect.collect(ym1, ym2, cache_dir=cache_dir, age=age)
    return render.render(data, meta), meta


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="전국 관광 현황을 한 장으로 정리한다")
    parser.add_argument("--out", default=None,
                        help="HTML을 쓸 경로. 없으면 표준출력")
    parser.add_argument("--from", dest="ym1", default=None, metavar="YYYYMM")
    parser.add_argument("--to", dest="ym2", default=None, metavar="YYYYMM")
    parser.add_argument("--age", default=None, choices=AGES,
                        help="인기 관광지를 볼 연령대. 없으면 전 연령")
    parser.add_argument("--cache-dir", default=None)
    args = parser.parse_args(argv)

    if (args.ym1 is None) != (args.ym2 is None):
        # 한쪽만 주면 나머지를 우리가 지어내야 한다. 사용자가 의도한
        # 창인지 알 수 없으므로 묻지 말고 거부한다.
        print("오류: --from 과 --to 는 함께 주거나 함께 비워야 합니다.",
              file=sys.stderr)
        return 2

    if args.ym1 is None:
        ym1, ym2 = collect.default_period()
    else:
        ym1, ym2 = args.ym1, args.ym2
        if period.span(ym1, ym2) < 1:
            print(f"오류: 기간이 거꾸로입니다: {ym1}~{ym2}", file=sys.stderr)
            return 2

    html, meta = build(ym1, ym2, cache_dir=args.cache_dir, age=args.age)

    if args.out:
        pathlib.Path(args.out).write_text(html, encoding="utf-8")
        print(f"리포트를 만들었습니다: {args.out}")
    else:
        print(html)

    print(f"기준 기간 {meta['기준기간']} · 수록 "
          f"{meta['수록지표']}/{meta['시도지표']}", file=sys.stderr)
    for key, reason in sorted(meta["미수록"].items()):
        print(f"  받지 못함 {key}: {reason}", file=sys.stderr)

    if meta["세션상태"] == "만료":
        return 3
    if meta["수록지표"] == 0:
        # 한 지표도 못 받았으면 리포트가 아니라 빈 껍데기다. 0으로
        # 끝내면 호출한 쪽이 성공으로 읽는다.
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
