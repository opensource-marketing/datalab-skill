"""관광지 이름을 CONT_ID로 바꾼다.

지역·국가 코드와 달리 관광지 코드는 **고정 표를 만들 수 없다.** 전국
관광지가 수천 개이고 데이터랩이 목록을 통째로 내려주지 않는다. 그래서
codes.py(네트워크를 타지 않는다)에 두지 않고 여기 따로 둔다.

찾기는 지역 안에서만 한다. 관광지 이름은 전국에서 유일하지 않다
("중앙시장"만 해도 여러 지역에 있다). 지역을 좁히지 않고 이름만으로
고르면 엉뚱한 곳의 숫자를 보게 된다.
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import client  # noqa: E402
import codes  # noqa: E402
import normalize  # noqa: E402
import workspace  # noqa: E402

CATALOG_PATH = (pathlib.Path(__file__).resolve().parents[1]
                / "catalog" / "poi_qid_catalog.yaml")
LIST_QID = "LN_05_01_011"
DEFAULT_PERIOD = ("202401", "202412")

_catalog_cache = None


class PoiError(Exception):
    """관광지를 찾을 수 없을 때. 사용자 입력이 원인이다."""


def load_catalog():
    global _catalog_cache
    if _catalog_cache is None:
        _catalog_cache = normalize.load_catalog(CATALOG_PATH)
    return _catalog_cache


def list_in_region(sgg_cd, *, ym1=None, ym2=None, cache_dir=None,
                   session_file=None):
    """한 시군구의 관광지를 모두 돌려준다. (CONT_ID, 이름, 분류) 목록."""
    ym1 = ym1 or DEFAULT_PERIOD[0]
    ym2 = ym2 or DEFAULT_PERIOD[1]
    params = {"SIDO_CD": str(sgg_cd)[:2], "SGG_CD": str(sgg_cd),
              "BASE_YM1": str(ym1), "BASE_YM2": str(ym2)}
    rows = normalize.fetch_qid(LIST_QID, params, catalog=load_catalog(),
                               cache_dir=cache_dir, session_file=session_file)
    found = []
    for row in rows:
        cont_id = str(row.get("CONT_ID") or "").strip()
        name = str(row.get("CONT_NM") or "").strip()
        if not cont_id or not name:
            continue
        found.append({
            "CONT_ID": cont_id,
            "관광지명": name,
            "분류": str(row.get("KTO_CATE_MCLS_NM") or "").strip(),
            "시군구": str(row.get("SGG_NM") or "").strip(),
        })
    return sorted(found, key=lambda r: r["관광지명"])


def search(name, region, *, ym1=None, ym2=None, cache_dir=None,
           session_file=None):
    """지역 안에서 이름으로 관광지를 찾는다.

    지역은 시군구 이름이나 코드다. 지역이 여러 곳에 걸리면 예외를 던진다 —
    관광지를 찾기 전에 지역부터 정해져야 한다.
    """
    hits = codes.resolve_region(region)
    if not hits:
        raise PoiError(f"일치하는 지역이 없습니다: {region}")
    if len(hits) > 1:
        lines = "\n".join(f"  {c}  {n}" for c, n in hits)
        raise PoiError(f"'{region}'에 여러 지역이 일치합니다. 하나를 골라 "
                       f"다시 실행하세요:\n{lines}")
    sgg_cd, region_name = hits[0]

    everything = list_in_region(sgg_cd, ym1=ym1, ym2=ym2, cache_dir=cache_dir,
                                session_file=session_file)
    if not everything:
        # 통합시(수원·전주 등)는 시 코드로 부르면 빈 배열이 오고 구
        # 코드로만 값이 온다. 시 이름으로 물은 사람에게 "관광지가
        # 없습니다"라고 답하지 않도록 산하 구를 뒤진다.
        for child_cd, child_name in codes.children(sgg_cd):
            found = list_in_region(child_cd, ym1=ym1, ym2=ym2,
                                   cache_dir=cache_dir,
                                   session_file=session_file)
            # 돌려받은 dict 를 제자리에서 고치지 않는다. 나중에 목록을
            # 캐시하게 되면 그 캐시를 오염시킨다.
            everything += [dict(row, 시군구=row.get("시군구") or child_name)
                           for row in found]
        everything.sort(key=lambda r: r.get("관광지명", ""))
    text = str(name).strip()
    if not text:
        return sgg_cd, region_name, everything
    hits = [r for r in everything if text in r["관광지명"]]
    if not hits and " " in text:
        # 사람은 "경포 해수욕장"이라고 띄어 쓴다. 데이터랩 표기가
        # 붙여쓰기라고 해서 사용자가 그렇게 써야 하는 것은 아니다.
        빈칸없이 = text.replace(" ", "")
        hits = [r for r in everything
                if 빈칸없이 in r["관광지명"].replace(" ", "")]
    return sgg_cd, region_name, hits


def resolve_one(name, region, **kwargs):
    """딱 하나로 좁혀질 때만 (CONT_ID, 이름)을 돌려준다.

    여러 곳에 걸리면 예외를 던진다. 임의로 하나를 고르면 사용자는 자기가
    묻지 않은 관광지의 숫자를 보게 된다.
    """
    _, region_name, hits = search(name, region, **kwargs)
    if not hits:
        raise PoiError(f"{region_name}에서 '{name}'"
                       f"{codes.josa(name, '을', '를')} 찾지 못했습니다.")
    if len(hits) > 1:
        lines = "\n".join(f"  {h['CONT_ID']}  {h['관광지명']} ({h['분류']})"
                          for h in hits[:20])
        more = f"\n  ... 모두 {len(hits)}곳" if len(hits) > 20 else ""
        raise PoiError(f"{region_name}에서 '{name}'에 여러 관광지가 "
                       f"일치합니다. 하나를 골라 다시 실행하세요:\n{lines}{more}")
    return hits[0]["CONT_ID"], hits[0]["관광지명"]


def main(argv=None):
    parser = argparse.ArgumentParser(description="관광지 이름을 CONT_ID로 바꾼다")
    parser.add_argument("name", nargs="?", default="",
                        help="관광지 이름 일부. 비우면 지역의 전체 목록")
    parser.add_argument("--region", required=True,
                        help="시군구 이름 또는 5자리 코드")
    parser.add_argument("--from", dest="ym1", default=None, metavar="YYYYMM")
    parser.add_argument("--to", dest="ym2", default=None, metavar="YYYYMM")
    # 기본값을 여기서 문자열로 박으면 workspace(작업 공간)와 어긋난다 —
    # None으로 두고 파싱 뒤에 workspace.*()로 채운다. --cache-dir/
    # --session-file을 직접 준 사용자의 값은 그대로 존중한다.
    parser.add_argument("--session-file", default=None)
    parser.add_argument("--cache-dir", default=None)
    args = parser.parse_args(argv)
    if args.session_file is None:
        args.session_file = str(workspace.session_file())
    if args.cache_dir is None:
        args.cache_dir = str(workspace.cache_dir())

    try:
        _, region_name, hits = search(
            args.name, args.region, ym1=args.ym1, ym2=args.ym2,
            cache_dir=args.cache_dir, session_file=args.session_file)
    except PoiError as exc:
        print(exc, file=sys.stderr)
        return 1
    except client.SessionExpired:
        print("세션이 만료됐습니다. datalab-auth 스킬로 갱신하세요.",
              file=sys.stderr)
        return 3
    except client.FetchError as exc:
        print(f"인출에 실패했습니다: {exc}", file=sys.stderr)
        return 4

    if not hits:
        print(f"{region_name}에서 '{args.name}'"
              f"{codes.josa(args.name, '을', '를')} 찾지 못했습니다.",
              file=sys.stderr)
        return 1
    print(f"# {region_name} · {len(hits)}곳")
    for hit in hits:
        print(f"{hit['CONT_ID']}\t{hit['관광지명']}\t{hit['분류']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
