import { useEffect, useState } from "react";

/** 景点图片：从后端 /api/attraction-image 取必应搜索的真实景点照片
 * （网络实测 Wikipedia/Openverse 被墙；picsum 只有随机图，与景点无关）。
 * 同一景点后端缓存结果，前端带 name 即取；失败回退占位块。 */
export default function AttractionImage({ name }: { name: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    fetch(`/api/attraction-image?name=${encodeURIComponent(name)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { url?: string | null } | null) => {
        if (!alive) return;
        setUrl(d?.url ?? null);
        setFailed(!d?.url);
      })
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [name]);

  return (
    <div className="relative mt-2 overflow-hidden rounded-lg">
      {url ? (
        <img
          src={url}
          alt={name}
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
          className="h-36 w-full object-cover"
        />
      ) : (
        !failed && (
          <div className="flex h-36 w-full items-center justify-center bg-slate-100 text-xs text-slate-400">
            图片加载中…
          </div>
        )
      )}
      {failed && (
        <div className="flex h-36 w-full items-center justify-center bg-slate-100 text-xs text-slate-400">
          图片加载失败
        </div>
      )}
    </div>
  );
}
