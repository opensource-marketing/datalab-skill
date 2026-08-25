"""지역 방문객 프로파일 리포트를 생성하는 CLI."""
import argparse
import pathlib
import sys

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (_SKILLS_ROOT / "datalab-fetch" / "scripts",
           _SKILLS_ROOT / "inbound-country-brief" / "scripts",
           _SKILLS_ROOT / "region-visitor-profile" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import client
import collect
import insight
import period
import codes
from render import render_report
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


def _build_comparisons(sections, meta, sgg_cd, ym1, ym2):
    """추이형 지표마다 전년·유사지역 비교를 계산한다."""
    peers = insight.similar_regions(meta)
    comparisons = {}
    for frames in sections.values():
        for qid, frame in frames.items():
            if qid not in insight.AGGREGATION:
                continue
            comparisons[qid] = {
                "전년": insight.yoy(qid, frame, sgg_cd, ym1, ym2,
                                    cache_dir=CACHE_DIR, session_file=SESSION_FILE),
                "유사": insight.vs_similar(qid, frame, peers, ym1, ym2,
                                           cache_dir=CACHE_DIR,
                                           session_file=SESSION_FILE),
            }
    return comparisons


def main(argv=None):
    parser = argparse.ArgumentParser(description="지역 방문객 프로파일")
    parser.add_argument("--region", required=True,
                        help="시군구 5자리 코드 또는 시군구 이름")
    period.add_arguments(parser)
    parser.add_argument("--out", required=True, help="출력 HTML 경로")
    parser.add_argument("--no-compare", action="store_true",
                        help="전년·유사지역 비교 계산을 건너뛴다(호출량 절감)")
    args = parser.parse_args(argv)

    try:
        args.ym1, args.ym2 = period.from_args(args, max_months=MAX_MONTHS)
    except period.PeriodError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    resolved = _resolve_region(args.region)
    if resolved is None:
        return 2
    sgg_cd, region_name = resolved

    note = codes.merged_city_note(sgg_cd)
    if note:
        # 오래 기다린 뒤 반쯤 빈 리포트를 보는 것보다, 부르기 전에
        # 아는 것을 말해 주는 편이 낫다.
        print(note, file=sys.stderr)


    try:
        sections, meta = collect.collect(sgg_cd, args.ym1, args.ym2,
                                         cache_dir=CACHE_DIR,
                                         session_file=SESSION_FILE)
    except client.SessionExpired:
        print("로그인 세션이 만료되었습니다. 다음 명령으로 세션을 갱신한 뒤 "
              f"다시 시도하세요:\n  {LOGIN_HINT}", file=sys.stderr)
        return 3
    except client.FetchError:
        print("데이터를 가져오지 못했습니다. 네트워크/프록시 상태를 확인하고, "
              f"다음 명령으로 세션 상태를 진단해보세요:\n  {CHECK_HINT}",
              file=sys.stderr)
        return 4

    if meta["수록지표"] == 0:
        # collect는 지표 단위로 실패를 삼키므로 예외를 던지지 않는다. 따라서
        # 위의 except 절은 모듈 경계 방어일 뿐이고, 세션 만료를 실제로
        # 종료코드로 옮기는 것은 여기다. meta["세션상태"]가 유일한 신호다.
        if meta["세션상태"] == "만료":
            print("로그인 세션이 만료되어 지표를 하나도 가져오지 못했습니다. "
                  f"다음 명령으로 세션을 갱신한 뒤 다시 시도하세요:\n  {LOGIN_HINT}",
                  file=sys.stderr)
            return 3
        lines = period.summarize_notes(meta.get("기간조정") or {})
        if lines:
            print("\n".join(lines), file=sys.stderr)
        print("수록 가능한 지표가 하나도 없습니다. 기간을 조정하거나 "
              f"다음 명령으로 세션 상태를 진단해보세요:\n  {CHECK_HINT}",
              file=sys.stderr)
        return 4

    comparisons = None
    if not args.no_compare:
        comparisons = _build_comparisons(sections, meta, sgg_cd, args.ym1, args.ym2)

    html = render_report(sections, meta, region_name=region_name,
                         comparisons=comparisons)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"리포트를 생성했습니다: {out} "
          f"(수록 {meta['수록지표']}/{meta['시도지표']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
