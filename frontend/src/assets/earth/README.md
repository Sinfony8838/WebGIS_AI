# 登录页地球插画（auth globe）

登录页现在通过 `AuthGlobe.tsx` 和 `d3-geo` 在浏览器中动态绘制正射投影地球。
`ne_110m_land.json` 是运行时使用的陆地数据；两个 `auth-globe-*.svg`
保留为静态设计基准和不依赖脚本的预览产物。地球仅作为品牌视觉元素使用，
**不承担测量、定位或教学判读功能**。

## 数据来源

- 数据集：Natural Earth 1:110m Land（`ne_110m_land.geojson`）
- 来源：https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_land.geojson
- 数据 SHA-256：`9e0729ee253ca7d7a5c4ae9395fb1902264c5377c52e224d13dd85010e2835d9`
- 许可证：Natural Earth 数据为公有领域（Public Domain，见
  https://www.naturalearthdata.com/about/terms-of-use/ ），无需署名；本文件即为溯源说明。
- 仅使用海岸线/陆地轮廓与经纬网，不含国界、国名或任何行政区划表达。

## 投影与绘制方法

- 正射投影（Orthographic），初始中心东经 105°、北纬 30°（面向东亚读者）。
- 陆地多边形先按大圆可见性（Sutherland–Hodgman 球面裁切）裁切到可见半球后投影；
  经纬网每 30° 一条，逐段裁切在球体内；赤道单独加亮。
- 装饰元素只有光晕与一条虚线轨道环，均为非数据化视觉元素，不表示任何真实数据。
- 页面加载后经度缓慢自转；用户可用鼠标或触控沿经纬方向拖动，并可双击恢复初始视角。
- `prefers-reduced-motion: reduce` 会停止自动旋转、光晕、轨道和鼠标视差；主动拖动仍可用。

## 重新生成

```powershell
cd tools
python generate_auth_globe.py
```

脚本会优先复用本目录缓存的 `ne_110m_land.geojson`，缺失时重新下载并打印其
SHA-256 以便核对。请勿手改生成的 SVG。
