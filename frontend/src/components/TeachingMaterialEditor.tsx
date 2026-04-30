import { useMemo, useState } from "react";
import type { KnowledgeBaseItem, RegionBinding, TeachingMaterial } from "../types";

type Props = {
  item: KnowledgeBaseItem;
  loading: boolean;
  onUpload: (file: File, metadata: { title: string; description: string; material_type: string; region_binding: RegionBinding }) => void;
  onAddLink: (payload: { url: string; title: string; description: string; material_type: string; region_binding: RegionBinding }) => void;
  onImportToLesson: (item: KnowledgeBaseItem, material?: TeachingMaterial) => void;
};

function materialLabel(type: string): string {
  if (type === "image") {
    return "图片";
  }
  if (type === "video") {
    return "视频";
  }
  if (type === "animation") {
    return "动画";
  }
  if (type === "document") {
    return "文档";
  }
  return "链接";
}

export function TeachingMaterialEditor({ item, loading, onUpload, onAddLink, onImportToLesson }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [materialType, setMaterialType] = useState("link");
  const [regionName, setRegionName] = useState(item.region || "");
  const [layerId, setLayerId] = useState(item.dataset_refs?.[0]?.layer_id || "");
  const materials = useMemo(() => item.materials || [], [item.materials]);

  const binding = (): RegionBinding => ({
    ...(regionName.trim() ? { name: regionName.trim() } : {}),
    ...(layerId.trim() ? { layer_id: layerId.trim() } : {})
  });

  return (
    <section className="kb-material-editor" data-testid="teaching-material-editor">
      <div className="kb-section-header">
        <strong>地区教学资料</strong>
        <button type="button" className="mini-control wide" onClick={() => onImportToLesson(item)} disabled={!item.id}>
          导入条目
        </button>
      </div>

      <div className="kb-material-list">
        {materials.length ? (
          materials.map((material) => (
            <article key={material.id} className="kb-material-card">
              <div>
                <span>{materialLabel(material.type)}</span>
                <strong>{material.title}</strong>
                <p>{material.description || material.region_binding?.name || "暂无说明"}</p>
              </div>
              <div className="kb-material-actions">
                {material.url ? (
                  <a href={material.url} target="_blank" rel="noreferrer">
                    预览
                  </a>
                ) : null}
                <button type="button" onClick={() => onImportToLesson(item, material)}>
                  加入课时
                </button>
              </div>
            </article>
          ))
        ) : (
          <div className="kb-empty">还没有为该地区添加图文、视频或动画资料。</div>
        )}
      </div>

      <div className="kb-material-form">
        <label>
          <span>绑定地区</span>
          <input value={regionName} onChange={(event) => setRegionName(event.target.value)} placeholder="如：长三角 / 广东省" />
        </label>
        <label>
          <span>关联图层</span>
          <input value={layerId} onChange={(event) => setLayerId(event.target.value)} placeholder="可选 layer_id" />
        </label>
        <label>
          <span>标题</span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="资料标题" />
        </label>
        <label>
          <span>类型</span>
          <select value={materialType} onChange={(event) => setMaterialType(event.target.value)}>
            <option value="link">链接</option>
            <option value="image">图片</option>
            <option value="video">视频</option>
            <option value="animation">动画</option>
            <option value="document">文档</option>
          </select>
        </label>
        <label className="wide">
          <span>说明</span>
          <textarea rows={2} value={description} onChange={(event) => setDescription(event.target.value)} />
        </label>
        <label className="wide">
          <span>外部链接</span>
          <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://..." />
        </label>
        <label className="wide">
          <span>本地文件</span>
          <input type="file" onChange={(event) => setFile(event.target.files?.[0] || null)} />
        </label>
      </div>

      <div className="kb-material-submit">
        <button
          type="button"
          className="tool-button"
          disabled={loading || !url.trim()}
          onClick={() => onAddLink({ url: url.trim(), title: title.trim(), description, material_type: materialType, region_binding: binding() })}
        >
          添加外链
        </button>
        <button
          type="button"
          className="tool-button"
          disabled={loading || !file}
          onClick={() => {
            if (file) {
              onUpload(file, { title: title.trim(), description, material_type: materialType, region_binding: binding() });
            }
          }}
        >
          上传素材
        </button>
      </div>
    </section>
  );
}
