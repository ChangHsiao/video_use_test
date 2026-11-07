// 動作函式：淡入的進度、彈出、線條一筆畫出、固定的偽隨機、秒數換格數

import {Easing, interpolate} from 'remotion';

// interpolate 超出範圍時停在頭尾，不繼續往外推
export const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

// 從第 start 格開始、花 len 格，從 0 走到 1；預設先慢、中間快、最後慢
export const progress = (frame: number, start: number, len: number, easing = Easing.inOut(Easing.cubic)) =>
  interpolate(frame, [start, start + len], [0, 1], {...clamp, easing});

// 彈出：0 → 放大到 1.25 倍 → 回到 1，共 12 格
export const pop = (frame: number, start: number) =>
  interpolate(frame, [start, start + 5, start + 12], [0, 1.25, 1], clamp);

// 線條一筆畫出：把回傳值展開到 SVG 的 path / rect / line 上，p 從 0 到 1 時線條從無到完整
export const drawStroke = (p: number) => ({pathLength: 1, strokeDasharray: 1, strokeDashoffset: 1 - p});

// 固定的偽隨機（0～1）：同一個 i 永遠得到同一個數，每次算繪結果都一樣
export const rand = (i: number) => {
  const x = Math.sin(i * 12.9898) * 43758.5453;
  return x - Math.floor(x);
};

// 秒數換成格數
export const sec = (s: number, fps = 30) => Math.round(s * fps);
