import type { ThemeConfig } from "antd";

/** 品牌色 —— 与 index.css 中 Tailwind @theme --color-brand 保持一致 */
export const BRAND = "#0d9488";

export const themeConfig: ThemeConfig = {
  token: {
    colorPrimary: BRAND,
    colorInfo: BRAND,
    colorLink: BRAND,
    borderRadius: 8,
    colorBgLayout: "#f2f7f6",
  },
};
