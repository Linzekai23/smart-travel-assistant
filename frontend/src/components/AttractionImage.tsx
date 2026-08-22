import { useState } from "react";

/** 景点图片：picsum seed 图（网络实测 Wikipedia/Openverse 被墙，
 * picsum 稳定可达）。按景点名做 seed，同一景点图片稳定不变；
 * "示例图片"标注与项目免责声明（AI 生成示例数据）精神一致。 */
export default function AttractionImage({ name }: { name: string }) {
  const [failed, setFailed] = useState(false);
  const src = `https://picsum.photos/seed/${encodeURIComponent(name)}/600/400`;
  return (
    <div className="relative mt-2 overflow-hidden rounded-lg">
      <img
        src={src}
        alt={name}
        loading="lazy"
        onError={() => setFailed(true)}
        className="h-36 w-full object-cover"
      />
      {failed ? (
        <div className="flex h-36 w-full items-center justify-center bg-slate-100 text-xs text-slate-400">
          图片加载失败
        </div>
      ) : (
        <span className="absolute bottom-0 right-0 rounded-tl bg-black/40 px-1.5 py-0.5 text-[10px] text-white">
          示例图片
        </span>
      )}
    </div>
  );
}
