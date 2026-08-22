import { useEffect, useState } from "react";

/** 景点/商家图片：优先高德真实照片直链（photoUrl，餐厅/酒店 100% 覆盖）；
 * 无则从后端 /api/attraction-image 取必应搜索（景点）。
 * city 用于消除搜索歧义（如"南桥"会命中主板芯片，需搜"都江堰 南桥"）。
 * 失败状态按当前图片键（name/city/photoUrl）记录：跨 replan 组件实例复用
 * （Timeline 同位置）时键变化即自动重置，无需 effect 里同步 setState。 */
const keyFor = (name: string, city: string | undefined, photoUrl: string | undefined) =>
  JSON.stringify([name, city ?? "", photoUrl ?? ""]);

export default function AttractionImage({
  name,
  city,
  photoUrl,
}: {
  name: string;
  city?: string;
  photoUrl?: string;
}) {
  const [searchedUrl, setSearchedUrl] = useState<string | null>(null);
  const [failedKey, setFailedKey] = useState<string | null>(null);
  const key = keyFor(name, city, photoUrl);
  const failed = failedKey === key;
  const url = photoUrl || searchedUrl;

  useEffect(() => {
    if (photoUrl) return; // 高德照片直链优先，无需搜索
    let alive = true;
    const params = new URLSearchParams({ name });
    if (city) params.set("city", city);
    fetch(`/api/attraction-image?${params.toString()}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { url?: string | null } | null) => {
        if (!alive) return;
        setSearchedUrl(d?.url ?? null);
        setFailedKey(d?.url ? null : keyFor(name, city, photoUrl));
      })
      .catch(() => alive && setFailedKey(keyFor(name, city, photoUrl)));
    return () => {
      alive = false;
    };
  }, [name, city, photoUrl]);

  return (
    <div className="relative mt-2 overflow-hidden rounded-lg">
      {url && !failed ? (
        <img
          src={url}
          alt={name}
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailedKey(key)}
          className="h-36 w-full object-cover"
        />
      ) : failed ? (
        <div className="flex h-36 w-full items-center justify-center bg-slate-100 text-xs text-slate-400">
          图片加载失败
        </div>
      ) : (
        <div className="flex h-36 w-full items-center justify-center bg-slate-100 text-xs text-slate-400">
          图片加载中…
        </div>
      )}
    </div>
  );
}
