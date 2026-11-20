// 3b1b 風格的說明動畫設定：複製去蓋過 edit/animations/src/theme.ts（規則見 styles/3b1b/STYLE.md）
// 欄位和 templates/remotion/src/theme.ts 一樣，零件不用改。
// 這個風格不用彈跳：不要用 motion.ts 的 pop，箭頭和圖形用 progress 平順地長出來。

export const theme = {
  font: '"Noto Serif CJK TC", "Noto Serif TC", "CMU Serif", serif',
  // 一個概念固定一個顏色，整支片不換。amber 在這裡是純黃，只用來表示「看這裡」
  colors: {
    red: '#fc6255',
    cyan: '#58c4dd',
    amber: '#ffff00',
    green: '#83c167',
    line: '#bbbbbb',
    muted: '#888888',
    subtle: '#bbbbbb',
    text: '#ffffff',
    outline: '#000000', // 文字描邊，讓字壓在圖形上也看得清楚
    accent: '#ffff00', // 標題重點字
  },
  // 全黑、沒有漸層、沒有格線
  background: {
    inner: '#000000',
    outer: '#000000',
    grid: 'rgba(255,255,255,0)',
    gridSize: 60,
  },
  title: {top: 210, smallSize: 40, bigSize: 90, bigWeight: 400},
  badge: {text: '示意圖', size: 30, gap: 215}, // gap：標籤離標題頂端多遠
};

export type Theme = typeof theme;
