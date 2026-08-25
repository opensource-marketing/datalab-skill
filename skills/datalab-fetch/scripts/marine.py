"""해양관광 지표에 필요한 배열 파라미터를 만든다.

해양관광(`BY_TH_MARINE_*`)만 파라미터 모양이 다르다. 지역의 연안 유형
목록을 배열로 함께 보내야 한다.

    A_1[0][YEONAN_TYPE_NM]=연안 도시
    A_1[0][YEONAN_TYPE_CD]=A01
    A_1[0][CNT]=4
    ...

이 값은 지어내는 것이 아니라 사이트가 먼저 부르는
`BY_TH_MARINE_COMMON_DISP_CHECK`이 돌려주는 것이다. 그래서 두 단계다.
지역마다 유형 구성이 다르므로(강릉시는 셋, 고성군은 둘) 카탈로그의
fixed_params로는 적을 수 없다.

네트워크를 타므로 codes.py에 두지 않았다. poi.py와 같은 이유다.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import client  # noqa: E402
import codes  # noqa: E402
import normalize  # noqa: E402
import workspace  # noqa: E402

CATALOG_PATH = (pathlib.Path(__file__).resolve().parents[1]
                / "catalog" / "theme_qid_catalog.yaml")
TYPES_QID = "BY_TH_MARINE_COMMON_DISP_CHECK"
# 유형 코드 A01/A02/A03 이 각각 A_1/A_2/A_3 자리에 들어간다.
SLOT_PREFIX = "A_"

_catalog_cache = None


class MarineError(Exception):
    """해양관광 파라미터를 만들 수 없을 때."""


def load_catalog():
    global _catalog_cache
    if _catalog_cache is None:
        _catalog_cache = normalize.load_catalog(CATALOG_PATH)
    return _catalog_cache


def base_params(sgg_cd, ym1, ym2):
    """연안 유형 조회에 쓰는 기본 파라미터."""
    return {"SGG_CD": str(sgg_cd), "SGG_NM": "", "BASE_YM1": str(ym1),
            "BASE_YM2": str(ym2), "srchAreaDate": "1", "tabDiv": "1",
            "srchDivType": "REGN"}


def coastal_types(sgg_cd, ym1, ym2, *, cache_dir=None, session_file=None):
    """그 지역의 연안 유형 목록. [(코드, 이름, 개수)]."""
    rows = normalize.fetch_qid(TYPES_QID, base_params(sgg_cd, ym1, ym2),
                               catalog=load_catalog(), cache_dir=cache_dir,
                               session_file=session_file)
    found = []
    for row in rows:
        code = str(row.get("연안유형코드") or row.get("YEONAN_TYPE_CD") or "").strip()
        name = str(row.get("연안유형") or row.get("YEONAN_TYPE_NM") or "").strip()
        count = row.get("개수", row.get("CNT"))
        if code and name:
            found.append((code, name, count))
    return found


def params_for(region, ym1, ym2, *, cache_dir=None, session_file=None):
    """지역 이름이나 코드로 해양관광 파라미터 한 벌을 만든다.

    (파라미터dict, 표시이름)을 돌려준다. 연안 유형이 하나도 없으면
    바다에 닿지 않는 지역이므로 예외를 던진다 — 빈 표를 돌려주는 것보다
    이유를 말하는 편이 낫다.
    """
    hits = codes.resolve_region(region)
    if not hits:
        raise MarineError(f"일치하는 지역이 없습니다: {region}")
    if len(hits) > 1:
        lines = "\n".join(f"  {c}  {n}" for c, n in hits)
        raise MarineError(f"'{region}'에 여러 지역이 일치합니다. 하나를 골라 "
                          f"다시 실행하세요:\n{lines}")
    sgg_cd, name = hits[0]

    types = coastal_types(sgg_cd, ym1, ym2, cache_dir=cache_dir,
                          session_file=session_file)
    if not types:
        raise MarineError(f"{name}에는 연안 유형이 없습니다. 해양관광 지표는 "
                          f"바다에 닿은 지역만 다룹니다.")

    params = base_params(sgg_cd, ym1, ym2)
    for code, type_name, count in types:
        slot = SLOT_PREFIX + code[-1]
        params[f"{slot}[0][YEONAN_TYPE_NM]"] = type_name
        params[f"{slot}[0][YEONAN_TYPE_CD]"] = code
        params[f"{slot}[0][CNT]"] = str(count)
    params["disp_yeoan_all"] = "N"
    params["itemType"] = "ALL"
    return params, name


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="해양관광 지표에 넣을 배열 파라미터를 만든다")
    parser.add_argument("region", help="시군구 이름 또는 5자리 코드")
    parser.add_argument("--from", dest="ym1", default="202401",
                        metavar="YYYYMM")
    parser.add_argument("--to", dest="ym2", default="202412", metavar="YYYYMM")
    # poi.py와 같은 이유로 None 기본값 뒤에 workspace.*()를 채운다.
    parser.add_argument("--session-file", default=None)
    parser.add_argument("--cache-dir", default=None)
    args = parser.parse_args(argv)
    if args.session_file is None:
        args.session_file = str(workspace.session_file())
    if args.cache_dir is None:
        args.cache_dir = str(workspace.cache_dir())

    try:
        params, name = params_for(args.region, args.ym1, args.ym2,
                                  cache_dir=args.cache_dir,
                                  session_file=args.session_file)
    except MarineError as exc:
        print(exc, file=sys.stderr)
        return 1
    except client.SessionExpired:
        print("세션이 만료됐습니다. datalab-auth 스킬로 갱신하세요.",
              file=sys.stderr)
        return 3
    except client.FetchError as exc:
        print(f"인출에 실패했습니다: {exc}", file=sys.stderr)
        return 4

    print(f"# {name}")
    print(json.dumps(params, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
