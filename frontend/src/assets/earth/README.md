# 登录页地球插画（auth globe）

本目录下的两个 SVG 是登录页的装饰性地理插画：`auth-globe-dark.svg`（深色主题）与
`auth-globe-light.svg`（浅色主题）。它们仅作为品牌视觉元素使用，**不承担测量、
定位或教学判读功能**；页面中以 `aria-hidden="true"` 的 `<img>` 引用。

## 数据来源

- 数据集：Natural Earth 1:110m Land（`ne_110m_land.geojson`）
- 来源：https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_land.geojson
- 数据 SHA-256：`9e0729ee253ca7d7a5c4ae9395fb1902264c5377c52e224d13dd85010e2835d9`
- 许可证：Natural Earth 数据为公有领域（Public Domain，见
  https://www.naturalearthdata.com/about/terms-of-use/ ），无需署名；本文件即为溯源说明。
- 仅使用海岸线/陆地轮廓与经纬网，不含国界、国名或任何行政区划表达。

## 投影与绘制方法

- 正射投影（Orthographic），投影中心东经 105°、北纬 30°（面向东亚读者）。
- 陆地多边形先按大圆可见性（Sutherland–Hodgman 球面裁切）裁切到可见半球后投影；
  经纬网每 30° 一条，逐段裁切在球体内；赤道单独加亮。
- 装饰元素只有光晕与一条虚线轨道环，均为非数据化视觉元素，不表示任何真实数据
  （无节点、无连线语义）。陆地与经纬网保持静态，仅光晕（14s 呼吸）与轨道环
  （18s 旋转）做低速循环，并在 SVG 内置 `prefers-reduced-motion: reduce` 时关闭。

## 重新生成

```powershell
cd tools
python generate_auth_globe.py
```

脚本会优先复用本目录缓存的 `ne_110m_land.geojson`，缺失时重新下载并打印其
SHA-256 以便核对。请勿手改生成的 SVG。
