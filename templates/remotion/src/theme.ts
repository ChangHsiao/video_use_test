// 說明動畫的色票、字型、底色和字級；換風格只改這個檔案（預設值照 sop/風格_暗色科技風.md）

export const theme = {
  font: '"Noto Sans CJK TC", sans-serif',
  // 重點色只用 red、cyan、amber、green；line、muted 給線條和次要文字
  colors: {
    red: '#ff5a3c',
    cyan: '#7fd8ff',
    amber: '#ffb340',
    green: '#5be08a',
    line: '#c9d1db',
    muted: '#8a93a0',
    subtle: '#aab3bf',
    text: '#ffffff',
    outline: '#0b0d10', // 文字描邊，讓字壓在圖形上也看得清楚
  },
  background: {
    inner: '#1c2129',
    outer: '#0b0d10',
    grid: 'rgba(255,255,255,0.035)',
    gridSize: 60,
  },
  title: {top: 210, smallSize: 40, bigSize: 90, bigWeight: 700},
  badge: {text: '示意圖', size: 30, gap: 215}, // gap：標籤離標題頂端多遠
};

export type Theme = typeof theme;
