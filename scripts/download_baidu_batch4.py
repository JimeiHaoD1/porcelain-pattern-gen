from __future__ import annotations

import csv
import pathlib
import urllib.request


QUERY_PAGE = (
    "https://image.baidu.com/search/index?tn=baiduimage&word="
    "%E7%BC%A0%E6%9E%9D%E8%8A%B1%E5%8D%89%20%E4%BA%8C%E6%96%B9%E8%BF%9E%E7%BB%AD%20%E7%BA%BF%E7%A8%BF"
)

ENTRIES = [
    ("https://b0.bdstatic.com/b80c201608a0dc8055e569cc5f9d865f.jpg", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_4998847290776761156"),
    ("https://b0.bdstatic.com/a4a5c9b52f9607e49ed5fd4ae326960c.jpg", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_5007289658752121908"),
    ("https://miaobi-lite.bj.bcebos.com/miaobi/5mao/b%27LV8xNzM1NDI4MDk0LjkyMTU2MjI%3D%27/0.png", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_4681956296989694132"),
    ("https://miaobi-lite.bj.bcebos.com/miaobi/5mao/b%275LqM5pa56L%2Be57ut57q55qC35Zu%2B5qGIXzE3MjU3MTIwMjQuMzA5MDUwNg%3D%3D%27/0.png", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_4701758952522806243"),
    ("https://miaobi-lite.cdn.bcebos.com/miaobi/5mao/b%275LqM5pa56L%2Be57ut57q55qC35Zu%2B5qGIXzE3MzQ3MjA5MDYuODIxNzM2%27/0.png", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_2503622963830244212"),
    ("https://b0.bdstatic.com/ad8c24e5642dbff24244af7894be0510.jpg", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_5740537230323105637"),
    ("https://miaobi-lite.cdn.bcebos.com/miaobi/5mao/b%275LqM5pa56L%2Be57ut566A5Y2V5Zu%2B5qGIXzE3MjgzMjgwMjIuODUyNTQ1Mw%3D%3D%27/0.png", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_4830479886731853415"),
    ("https://gips2.baidu.com/it/u=3113366759,1858243935&fm=3074&app=3074&f=JPEG?w=1616&h=1998&type=normal&func=T", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_4530840685999081156"),
    ("https://miaobi-lite.bj.bcebos.com/miaobi/5mao/b%275LqM5pa56L%2Be57ut57q55qC35Zu%2B5qGIXzE3MzQ3MjA5MTcuNDI3MDcxMw%3D%3D%27/0.png", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_4756295300401601077"),
    ("https://pic.rmb.bdstatic.com/bjh/240312/events/101b02d7d61e031fba487b8d9935acce6217.jpeg", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_5514871045601226949"),
    ("https://gips0.baidu.com/it/u=4253174857,199818687&fm=3074&app=3074&f=JPEG?w=1080&h=1497&type=normal&func=", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_4394862789968103634"),
    ("https://miaobi-lite.bj.bcebos.com/miaobi/5mao/b%275LqM5pa56L%2Be57ut57q55qC35Zu%2B5qGIXzE3MjYzMzkyMDkuMTc5Nzc0NQ%3D%3D%27/0.png", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_3837110786458138898"),
    ("https://gips2.baidu.com/it/u=2092477421,3870486591&fm=3074&app=3074&f=JPEG?w=1280&h=873&type=normal&func=", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_4475308021398129518"),
    ("https://b0.bdstatic.com/d41f0e688666a395333b70c2ce777e05.jpg", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_4883239591432697097"),
    ("https://miaobi-lite.bj.bcebos.com/miaobi/5mao/b%27LV8xNzM1NDI4NTMwLjM3MDEyNg%3D%3D%27/0.png", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_4863785618891377210"),
    ("https://miaobi-lite.bj.bcebos.com/miaobi/5mao/b%275LqM5pa56L%2Be57ut57q55qC35Zu%2B5qGIXzE3MzYwOTU5ODkuMDY3MDMzMw%3D%3D%27/0.png", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_4558543628661580571"),
    ("https://miaobi-lite.bj.bcebos.com/miaobi/5mao/b%275Y236I2J57q55Zu%2B5qGI55qE5a%2BT5oSPXzE3MzQxOTc4NjcuMDIwOTk4Nw%3D%3D%27/0.png", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_4081323185091227643"),
    ("https://gips0.baidu.com/it/u=301967215,1184854175&fm=3074&app=3074&f=JPEG", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_5132050379844715318"),
    ("https://gips2.baidu.com/it/u=2619114013,1300719159&fm=3074&app=3074&f=JPEG", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_5447040610097191889"),
    ("https://p7.itc.cn/q_70/images03/20230427/29d62741ebcf422d970d7d3a7b0886fb.jpeg", "http://news.sohu.com/a/670990051_121124305"),
    ("https://gimg2.baidu.com/image_search/src=http%3A%2F%2Fsafe-img.xhscdn.com%2Fbw1%2F14f96f05-879a-4100-87c3-a888dc207d41%3FimageView2%2F2%2Fw%2F1080%2Fformat%2Fjpg&refer=http%3A%2F%2Fsafe-img.xhscdn.com&app=2002&size=f9999,10000&q=a80&n=0&g=0n&fmt=auto?sec=1786715242&t=a2e9265e7ed23d87a3381397fb70b780", "http://www.xiaohongshu.com/discovery/item/625e2d2a000000002103949b"),
    ("https://c-ssl.dtstatic.com/uploads/blog/202308/31/DWS6jP7JidWzXgN.thumb.1000_0.jpg", "http://www.duitang.com/blog/?id=1490370131"),
    ("https://gimg2.baidu.com/image_search/src=http%3A%2F%2Fsafe-img.xhscdn.com%2Fbw1%2F8d17712c-ad8a-45d9-b348-8f3ae2967706%3FimageView2%2F2%2Fw%2F1080%2Fformat%2Fjpg&refer=http%3A%2F%2Fsafe-img.xhscdn.com&app=2002&size=f9999,10000&q=a80&n=0&g=0n&fmt=auto?sec=1786715242&t=f2e67b88f100abf3ab65da7e9c742a01", "http://www.xiaohongshu.com/discovery/item/6396cc26000000001f0272d4"),
    ("https://www.yzjiaozhai.com/uploads/2/253/3510577842/125000924.jpg", "http://www.yzjiaozhai.com/e66466324b5ea1d0.html"),
    ("https://gips0.baidu.com/it/u=893632682,1564339654&fm=3074&app=3074&f=JPEG", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_4608161599357957447"),
    ("https://gips3.baidu.com/it/u=3490018762,1039586706&fm=3074&app=3074&f=JPEG", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_3720177179449620076"),
    ("https://p2.itc.cn/q_70/images03/20230427/c544a4b9cb934d05a7dbf7ac4e109aeb.jpeg", "http://news.sohu.com/a/670990051_121124305"),
    ("https://c-ssl.dtstatic.com/uploads/item/201906/29/20190629203655_CX2Yh.thumb.1000_0.jpeg", "http://www.duitang.com/blog/?id=1097229786"),
    ("https://miaobi-lite.bj.bcebos.com/miaobi/5mao/b%2757yg5p6d57q55Zu%2B5qGIXzE3Mjc0ODUwMTcuMzM0ODA5OA%3D%3D%27/0.png", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_5250945154876268063"),
    ("https://miaobi-lite.bj.bcebos.com/miaobi/5mao/b%2757yg5p6d6I6y5a%2BT5oSPXzE3Mjg4OTU0NzkuMjY1Mjg1Nw%3D%3D%27/0.png", "http://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_4097468757546048022"),
]


def main() -> None:
    out_dir = pathlib.Path(__file__).resolve().parents[1] / "data" / "source_candidates" / "web_independent_batch4_20260715" / "original_sources" / "baidu_image_query_01"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    for index, (image_url, source_page) in enumerate(ENTRIES, start=1):
        request = urllib.request.Request(
            image_url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": QUERY_PAGE},
        )
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                data = response.read()
                content_type = response.headers.get_content_type()
            extension = {"image/png": ".png", "image/webp": ".webp"}.get(content_type, ".jpg")
            path = out_dir / f"baidu_q01_{index:03d}{extension}"
            path.write_bytes(data)
            status = "downloaded"
        except Exception as exc:  # noqa: BLE001
            path = pathlib.Path("")
            content_type = ""
            status = f"error: {exc}"
        rows.append(
            {
                "index": str(index),
                "filename": path.name,
                "source_page": source_page,
                "direct_image_url": image_url,
                "query_page": QUERY_PAGE,
                "content_type": content_type,
                "status": status,
            }
        )
        print(index, status, path.name)

    with (out_dir / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
