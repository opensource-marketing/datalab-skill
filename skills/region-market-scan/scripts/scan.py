"""지역 관광시장 스캔 리포트를 생성하는 CLI."""
import argparse
import pathlib
import sys

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (_SKILLS_ROOT / "datalab-fetch" / "scripts",
           _SKILLS_ROOT / "inbound-country-brief" / "scripts",
           _SKILLS_ROOT / "region-market-scan" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import client
import codes
import market_collect as collect
import period
import market_metrics as metrics
from market_render import render_report
import workspace  # noqa: E402

CACHE_DIR = workspace.cache_dir()
SESSION_FILE = workspace.session_file()
MAX_MONTHS = 18
LOGIN_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "login.py")
CHECK_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "check_session.py")


def _resolve_region(query):
    """--region 값을 (코드, 표시이름)으로 해석한다. 실패하면 None."""
    if codes.is_sido(query):   # 숫자 두 자리만 참이다
        print(f"시도 코드({query})는 지원하지 않습니다. 시군구 5자리 코드나 "
              f"시군구 이름을 넣으세요.", file=sys.stderr)
        return None

    hits = codes.resolve_region(query)
    if not hits:
        print(f"일치하는 지역이 없습니다: {query}", file=sys.stderr)
        # 세종은 시군구 271곳에 없고 시도로만 있다. 틀린 이름과 축이 다른
        # 지역을 구분해 주지 않으면 사용자는 표기를 고쳐 가며 헛돈다.
        hint = codes.sido_hint(query)
        if hint:
            print(hint, file=sys.stderr)
        return None
    if len(hits) > 1:
        print(f"'{query}'에 여러 지역이 일치합니다. 하나를 골라 다시 실행하세요:",
              file=sys.stderr)
        for code, name in hits:
            print(f"  {code}  {name}", file=sys.stderr)
        hint = codes.sido_hint(query)
        if hint:
            print(hint, file=sys.stderr)
        return None
    return hits[0]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="지역 관광시장 스캔 리포트를 만든다")
    parser.add_argument("--region", required=True,
                        help="시군구 이름 또는 5자리 코드")
    period.add_arguments(parser)
    parser.add_argument("--out", required=True, metavar="FILE")
    parser.add_argument("--no-compare", action="store_true",
                        help="유사지역 비교를 건너뛴다(호출 수가 줄어든다)")
    args = parser.parse_args(argv)

    try:
        args.ym1, args.ym2 = period.from_args(args, max_months=MAX_MONTHS)
    except period.PeriodError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    resolved = _resolve_region(args.region)
    if resolved is None:
        return 2
    sgg_cd, region_name = resolved

    note = codes.merged_city_note(sgg_cd)
    if note:
        # 오래 기다린 뒤 반쯤 빈 리포트를 보는 것보다, 부르기 전에
        # 아는 것을 말해 주는 편이 낫다.
        print(note, file=sys.stderr)


    compare = not args.no_compare
    try:
        sections, meta = collect.collect(
            sgg_cd, args.ym1, args.ym2,
            cache_dir=str(CACHE_DIR), session_file=str(SESSION_FILE))
        derived = metrics.build(sections, meta, args.ym1, args.ym2,
                                region_name=region_name,
                                cache_dir=str(CACHE_DIR),
                                session_file=str(SESSION_FILE),
                                compare=compare)
    except client.SessionExpired:
        # collect는 지표 단위로 실패를 삼키므로 여기까지 오지 않는 것이
        # 보통이다. 모듈 경계 방어로만 남긴다.
        print(f"세션이 만료됐습니다. 다음을 실행하세요:\n  {LOGIN_HINT}",
              file=sys.stderr)
        return 3

    if meta["수록지표"] == 0:
        # collect가 예외를 던지지 않으므로, 세션 만료를 종료코드로 옮기는
        # 것은 여기다. meta["세션상태"]가 유일한 신호다.
        if meta["세션상태"] == "만료":
            print(f"세션이 만료되어 지표를 하나도 가져오지 못했습니다. "
                  f"다음을 실행하세요:\n  {LOGIN_HINT}", file=sys.stderr)
            return 3
        lines = period.summarize_notes(meta.get("기간조정") or {})
        if lines:
            # 기간이 원인인 것을 이미 알고 있으면서 "확인하세요"라고만
            # 말하면 사용자는 무엇을 확인해야 하는지 모른다.
            print("\n".join(lines), file=sys.stderr)
            print(f"요청한 기간({args.ym1}~{args.ym2})에는 이 지역의 지표가 "
                  f"하나도 없습니다. 기간을 앞당겨 보세요.", file=sys.stderr)
            return 4
        print(f"지표를 하나도 가져오지 못했습니다. 지역코드와 기간을 "
              f"확인하세요.\n  {CHECK_HINT}", file=sys.stderr)
        return 4

    html = render_report(sections, meta, derived,
                         region_name=region_name, compare=compare)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"리포트를 생성했습니다: {out} "
          f"(수록 {meta['수록지표']}/{meta['시도지표']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
