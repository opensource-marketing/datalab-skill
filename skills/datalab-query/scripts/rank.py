"""지표 하나를 전국 시군구로 훑어 순위를 낸다.

"어디를 볼지"는 "거기가 어떤지"보다 앞서는 질문이다. 기존 도구는 지역을
정해 놓고 물어야 했다. 이 스크립트는 반대로 묻는다 — 일본인 방문자가
가장 많은 시군구는? 외국인 카드소비가 가장 큰 곳은?

**비율 컬럼을 더하지 않는다.** 카탈로그의 단위가 %인 컬럼에 합계를
요구하면 거부한다. 비율을 지역끼리 더하면 아무 뜻도 없는 숫자가 나오는데,
숫자는 나오기 때문에 틀린 줄 모른다.
"""
import argparse
import pathlib
import sys
import time

import pandas as pd

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (_SKILLS_ROOT / "datalab-fetch" / "scripts",
           _SKILLS_ROOT / "datalab-query" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import client
import codes
import period
import query
import table
import workspace  # noqa: E402

CACHE_DIR = workspace.cache_dir()
SESSION_FILE = workspace.session_file()
DEFAULT_TOP = 20
REGION_COLUMN = "지역"
RATE_UNITS = {"%"}
AGGREGATIONS = ("sum", "mean", "max", "min", "last")
# 비율 컬럼에 쓸 수 있는 집계. 지역끼리 더하는 것만 막는다.
RATE_AGGREGATIONS = ("mean", "max", "min", "last")


class RankError(Exception):
    """순위를 낼 수 없을 때. 사용자 입력이 원인이다."""


def column_unit(qid, column):
    """카탈로그가 적어 둔 컬럼 단위를 돌려준다. 모르면 None."""
    source, holder = query.find_qid(qid)
    if source not in query.CATALOG_FILES:
        return None
    for meta in holder[qid]["columns"].values():
        if meta["label"] == column:
            return meta.get("unit")
    return None


def catalog_labels(qid):
    """카탈로그가 아는 컬럼 라벨 목록. 미검증 지표면 None."""
    source, holder = query.find_qid(qid)
    if source not in query.CATALOG_FILES:
        return None
    return [meta["label"] for meta in holder[qid]["columns"].values()]


def check_aggregation(qid, column, agg):
    """비율 컬럼을 더하려 하면 거부한다.

    지역끼리 비율을 더하면 뜻이 없다. 그런데 숫자는 나오기 때문에 틀린
    줄 모른다. 조용히 틀리느니 멈추는 편이 낫다.

    **컬럼 이름도 여기서 본다.** 오타 하나로 271곳을 다 부른 뒤에야
    "값이 나온 지역이 없습니다"를 듣는 것은 몇 분을 버리는 일이다.
    검증된 지표는 카탈로그가 컬럼을 알고 있으므로 부르기 전에 멈출 수
    있다.
    """
    if agg not in AGGREGATIONS:
        raise RankError(f"모르는 집계 방식입니다: {agg}")
    labels = catalog_labels(qid)
    if labels is not None and column not in labels:
        raise RankError(
            f"'{column}' 컬럼이 {qid}에 없습니다.\n"
            f"  쓸 수 있는 컬럼: {', '.join(labels)}")
    unit = column_unit(qid, column)
    if unit in RATE_UNITS and agg not in RATE_AGGREGATIONS:
        raise RankError(
            f"'{column}'{codes.josa(column, '은', '는')} 비율(%) "
            f"컬럼입니다. 지역끼리 더하면 뜻이 "
            f"없습니다.\n  --agg 로 {', '.join(RATE_AGGREGATIONS)} 중 "
            f"하나를 고르세요.")
    return unit


def targets(sido=None):
    """훑을 시군구 목록을 정한다. (코드, 표시이름)."""
    table_ = codes.load_codes()
    if sido is None:
        return sorted((code, codes.display_name(code, table_))
                      for code in table_)
    hits = codes.resolve_sido(sido)
    if not hits:
        raise RankError(f"일치하는 시도가 없습니다: {sido}")
    if len(hits) > 1:
        lines = "\n".join(f"  {c}  {n}" for c, n in hits)
        raise RankError(f"'{sido}'에 여러 시도가 일치합니다:\n{lines}")
    prefix = hits[0][0]
    picked = sorted((code, codes.display_name(code, table_))
                    for code in table_ if code.startswith(prefix))
    if not picked:
        raise RankError(f"{hits[0][1]}에 시군구가 없습니다. "
                        f"세종처럼 산하 시군구가 없는 시도입니다.")
    return picked


def parse_filters(items):
    """--where 컬럼=값 을 dict로 바꾼다."""
    filters = {}
    for item in items or ():
        if "=" not in item:
            raise RankError(f"--where 는 컬럼=값 형식이어야 합니다: {item}")
        key, value = item.split("=", 1)
        filters[key.strip()] = value.strip()
    return filters


def apply_filters(frame, filters):
    """행 필터를 적용한다. 없는 컬럼을 걸면 조용히 넘어가지 않는다."""
    for key, value in filters.items():
        if key not in frame.columns:
            raise RankError(f"'{key}' 컬럼이 응답에 없습니다. "
                            f"있는 컬럼: {', '.join(frame.columns)}")
        frame = frame[frame[key].astype(str) == value]
    return frame


def aggregate(frame, column, agg):
    """한 지역의 값을 하나로 줄인다. 값이 없으면 None."""
    if column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return None
    if agg == "sum":
        return float(values.sum())
    if agg == "mean":
        return float(values.mean())
    if agg == "max":
        return float(values.max())
    if agg == "min":
        return float(values.min())
    return float(values.iloc[-1])


def sweep(qid, column, *, agg="sum", filters=None, sido=None, ym1=None,
          ym2=None, cache_dir=None, session_file=None, progress=None):
    """시군구를 모두 훑어 (순위표, meta)를 만든다."""
    unit = check_aggregation(qid, column, agg)
    places = targets(sido)
    filters = filters or {}

    rows = []
    missing = {}
    for index, (code, name) in enumerate(places, start=1):
        if progress:
            progress(index, len(places), name)
        try:
            frame, _ = query.run(qid, regions=[code], ym1=ym1, ym2=ym2,
                                 cache_dir=cache_dir, session_file=session_file)
        except client.SessionExpired:
            missing[name] = "세션만료"
            break
        except client.FetchError:
            missing[name] = "인출실패"
            continue
        except query.QueryError as exc:
            raise RankError(str(exc)) from exc
        if frame.empty:
            missing[name] = "데이터없음"
            continue
        # 미검증 지표는 카탈로그가 컬럼을 모른다. 첫 응답이 컬럼을
        # 말해 주므로 여기서 멈춘다 — 나머지 270곳을 부를 이유가 없다.
        if column not in frame.columns:
            raise RankError(
                f"'{column}' 컬럼이 응답에 없습니다. {name} 응답의 "
                f"컬럼:\n  {', '.join(str(c) for c in frame.columns)}")
        value = aggregate(apply_filters(frame, filters), column, agg)
        if value is None:
            missing[name] = "값없음"
            continue
        rows.append({REGION_COLUMN: name, column: value})

    meta = {"qid": qid, "컬럼": column, "집계": agg, "단위": unit or "미상",
            "조건": filters, "기준기간": f"{ym1 or '-'}~{ym2 or '-'}",
            "훑은지역수": len(places), "값있는지역수": len(rows),
            "미수록": missing,
            "세션상태": "만료" if "세션만료" in missing.values() else "정상"}
    if not rows:
        return pd.DataFrame(), meta
    frame = pd.DataFrame(rows).sort_values(column, ascending=False,
                                           kind="mergesort")
    frame.insert(0, "순위", range(1, len(frame) + 1))
    return frame.reset_index(drop=True), meta


def _header(meta):
    lines = [f"{meta['qid']} · {meta['컬럼']} ({meta['단위']}) · "
             f"{meta['집계']} · {meta['기준기간']}"]
    if meta["조건"]:
        lines.append("행 필터: " + ", ".join(f"{k}={v}"
                                             for k, v in meta["조건"].items()))
    lines.append(f"시군구 {meta['훑은지역수']}곳 중 값이 나온 곳 "
                 f"{meta['값있는지역수']}곳")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="지표 하나를 전국 시군구로 훑어 순위를 낸다")
    parser.add_argument("--qid", required=True)
    parser.add_argument("--column", required=True,
                        help="순위를 매길 컬럼의 한글 라벨")
    parser.add_argument("--agg", default="sum", choices=AGGREGATIONS)
    parser.add_argument("--where", action="append", default=[],
                        metavar="컬럼=값", help="집계 전에 거를 행 조건")
    parser.add_argument("--sido", default=None,
                        help="한 시도로 좁힌다. 없으면 전국 271곳을 훑는다(3분쯤)")
    parser.add_argument("--period", default=None, metavar="기간",
                        help=period.HELP)
    parser.add_argument("--from", dest="ym1", metavar="YYYYMM")
    parser.add_argument("--to", dest="ym2", metavar="YYYYMM")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP,
                        help="보여줄 상위 개수. 0이면 전부")
    parser.add_argument("--format", default="table",
                        choices=sorted(table.RENDERERS))
    parser.add_argument("--out", metavar="FILE")
    parser.add_argument("--quiet", action="store_true", help="진행 표시 없음")
    args = parser.parse_args(argv)

    # 여기서는 --from 만 주거나 기간을 아예 안 주는 것도 정상이다.
    # 시점 재고 지표는 BASE_YM2 하나로 시점을 정한다.
    try:
        args.ym1, args.ym2 = period.from_args(
            args, anchor=period.ceiling(args.qid), allow_open_range=True)
    except period.PeriodError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    def progress(done, total, name):
        if args.quiet:
            return
        print(f"\r  {done}/{total} {name}          ", end="", file=sys.stderr)

    started = time.monotonic()
    try:
        frame, meta = sweep(
            args.qid, args.column, agg=args.agg,
            filters=parse_filters(args.where), sido=args.sido,
            ym1=args.ym1, ym2=args.ym2, cache_dir=str(CACHE_DIR),
            session_file=str(SESSION_FILE), progress=progress)
    except RankError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"\r  {time.monotonic() - started:.0f}초 걸렸습니다."
              f"{' ' * 30}", file=sys.stderr)

    if frame.empty:
        if meta["세션상태"] == "만료":
            print("세션이 만료됐습니다. datalab-auth 스킬로 갱신하세요.",
                  file=sys.stderr)
            return 3
        gap = period.explain_gap(args.qid, args.ym1, args.ym2)
        if gap:
            print(gap, file=sys.stderr)
        print("값이 나온 지역이 없습니다. qid와 컬럼 이름을 확인하세요.",
              file=sys.stderr)
        return 4

    limit = None if args.top == 0 else args.top
    body = table.render(frame, args.format, limit)
    if args.out:
        pathlib.Path(args.out).write_text(body + "\n", encoding="utf-8")
        print(f"{len(frame)}행을 저장했습니다: {args.out}")
        return 0

    if args.format in ("table", "md"):
        print(_header(meta))
        print()
    print(body)
    if args.format in ("table", "md"):
        print("\n" + table.SOURCE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
