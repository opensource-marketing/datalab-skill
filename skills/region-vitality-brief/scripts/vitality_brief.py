"""지역 활력 브리프 CLI.

인자 검증 · 종료 코드 · 파일 쓰기만 한다. 인출은 vitality_collect가,
HTML은 vitality_render가 맡는다.
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

import codes  # noqa: E402
import workspace  # noqa: E402

LOGIN_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "login.py")
import vitality_collect as collect  # noqa: E402
import vitality_render as render  # noqa: E402


def build(sgg_cd, region_name, y1, y2, *, cache_dir=None):
    data, meta = collect.collect(sgg_cd, region_name, y1, y2,
                                 cache_dir=cache_dir)
    return render.render(data, meta), meta


def _resolve(query):
    """지역 이름을 코드로. 여러 곳에 걸리면 후보를 보여 주고 멈춘다.

    하나를 골라 주지 않는다 — 강원 고성과 경남 고성 가운데 어느 쪽인지
    우리가 정하면 사용자는 다른 지역 리포트를 받고도 모른다.
    """
    hits = codes.resolve_region(query)
    if not hits:
        print(f"오류: '{query}'에 맞는 시군구를 찾지 못했습니다.",
              file=sys.stderr)
        hint = codes.sido_hint(query)
        if hint:
            print(hint, file=sys.stderr)
        return None
    if len(hits) > 1:
        print(f"'{query}'에 여러 곳이 걸립니다. 하나를 골라 다시 "
              f"실행하세요:", file=sys.stderr)
        for code, name in hits:
            print(f"  {code}  {name}", file=sys.stderr)
        return None
    return hits[0]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="지역이 버티고 있는지, 관광이 그것을 얼마나 메우는지")
    parser.add_argument("--region", required=True,
                        help="시군구 이름 또는 5자리 코드")
    parser.add_argument("--out", default=None,
                        help="HTML을 쓸 경로. 없으면 표준출력")
    parser.add_argument("--from", dest="y1", default=None, metavar="YYYY")
    parser.add_argument("--to", dest="y2", default=None, metavar="YYYY")
    parser.add_argument("--cache-dir", default=None)
    args = parser.parse_args(argv)

    resolved = _resolve(args.region)
    if resolved is None:
        return 2
    sgg_cd, region_name = resolved

    note = codes.merged_city_note(sgg_cd)
    if note:
        # 다른 리포트 스킬과 같이, 오래 기다린 뒤 반쯤 빈 리포트를 보는
        # 것보다 부르기 전에 아는 것을 말해 주는 편이 낫다.
        print(note, file=sys.stderr)

    if codes.is_sido(sgg_cd):
        # 시도 두 자리를 넣으면 그 시도의 시군구가 모두 섞여 온다.
        # 한 지역 리포트로 그리면 남의 값을 이 지역 값으로 읽는다.
        print("오류: 이 리포트는 시군구 단위입니다. 시도 코드로는 여러 "
              "시군구가 섞여 옵니다.", file=sys.stderr)
        return 2

    if (args.y1 is None) != (args.y2 is None):
        print("오류: --from 과 --to 는 함께 주거나 함께 비워야 합니다.",
              file=sys.stderr)
        return 2

    if args.y1 is None:
        y1, y2 = collect.default_period()
    else:
        y1, y2 = args.y1, args.y2
        for year in (y1, y2):
            if not (len(year) == 4 and year.isdigit()):
                # 월(202401)을 넣으면 오류가 아니라 빈 배열이 온다.
                # 그대로 두면 "이 지역엔 데이터가 없다"로 읽힌다.
                print(f"오류: 이 리포트의 기간은 연도 네 자리입니다: {year}",
                      file=sys.stderr)
                return 2
        if int(y1) > int(y2):
            print(f"오류: 기간이 거꾸로입니다: {y1}~{y2}", file=sys.stderr)
            return 2

    html, meta = build(sgg_cd, region_name, y1, y2, cache_dir=args.cache_dir)

    if args.out:
        out = pathlib.Path(args.out)
        # 상위 디렉터리가 없으면 트레이스백이 뜬다. 다른 리포트 스킬과
        # 같은 모양으로 맞춘다.
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        print(f"리포트를 만들었습니다: {args.out}")
    else:
        print(html)

    print(f"{region_name}({sgg_cd}) {meta['기준기간']} · 수록 "
          f"{meta['수록지표']}/{meta['전체지표']}", file=sys.stderr)
    for key, reason in sorted(meta["미수록"].items()):
        print(f"  받지 못함 {key}: {reason}", file=sys.stderr)
    for warning in meta["검산경고"]:
        print(f"  검산 경고: {warning}", file=sys.stderr)

    # 지표 하나가 만료를 만났다고 3을 돌려주면 호출한 쪽이 "실패했다"로
    # 읽는다. 리포트 파일은 이미 썼고 나머지 지표는 다 들어 있다.
    # 3은 아무것도 못 받았을 때만 낸다.
    if meta["수록지표"] == 0:
        if meta["세션상태"] == "만료":
            print(f"세션이 만료됐습니다. 다음을 실행하세요:\n  {LOGIN_HINT}",
                  file=sys.stderr)
            return 3
        print("지표를 하나도 받지 못했습니다. 지역코드와 연도를 "
              "확인하세요.", file=sys.stderr)
        return 1
    if meta["세션상태"] == "만료":
        print(f"일부 지표를 세션 만료로 받지 못했습니다. 필요하면:\n"
              f"  {LOGIN_HINT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
