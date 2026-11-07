// 箭頭：從起點往上下左右其中一個方向長出去，可以附一行文字；用來表示力、移動、流動的方向

import React from 'react';
import {Easing, useCurrentFrame} from 'remotion';
import {theme} from '../theme';
import {progress} from './motion';

type Dir = 'left' | 'right' | 'up' | 'down';
const VEC: Record<Dir, [number, number]> = {left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1]};

// (x, y) 是起點，len 是長到最長時的長度；bob 讓箭頭長完後沿方向輕輕晃動，強調「持續在推」
export const Arrow: React.FC<{
  x: number; y: number; dir: Dir; len: number; start: number;
  color?: string; width?: number; text?: string; fontSize?: number; bob?: boolean; glow?: boolean;
}> = ({x, y, dir, len, start, color = theme.colors.red, width = 12, text, fontSize = 44, bob = false, glow = false}) => {
  const frame = useCurrentFrame();
  const p = progress(frame, start, 12, Easing.out(Easing.back(1.6)));
  const [dx, dy] = VEC[dir];
  const shake = bob ? Math.sin((frame - start) * 0.4) * 6 * p : 0;
  const x0 = x + dx * shake;
  const y0 = y + dy * shake;
  const x1 = x0 + dx * len * p;
  const y1 = y0 + dy * len * p;
  const head = width * 2.25; // 箭頭尖端的長度
  const half = width * 1.75; // 箭頭底邊的一半寬
  const tip = `${x1 + dx * head},${y1 + dy * head}`;
  const side1 = `${x1 - dy * half},${y1 + dx * half}`;
  const side2 = `${x1 + dy * half},${y1 - dx * half}`;
  // 文字放在箭身中段的外側：水平箭頭寫在下方，垂直箭頭寫在右邊
  const tx = x0 + dx * len * 0.5 + (dy !== 0 ? fontSize * 1.2 : 0);
  const ty = y0 + dy * len * 0.5 + (dx !== 0 ? fontSize * 1.6 : 0);
  return (
    <g opacity={p > 0 ? 1 : 0} filter={glow ? 'url(#glow)' : undefined}>
      <line x1={x0} y1={y0} x2={x1} y2={y1} stroke={color} strokeWidth={width} strokeLinecap="round" />
      <polygon points={`${tip} ${side1} ${side2}`} fill={color} />
      {text && (
        <text x={tx} y={ty} fill={color} fontSize={fontSize} fontWeight={900}
          textAnchor={dy !== 0 ? 'start' : 'middle'} opacity={p}>{text}</text>
      )}
    </g>
  );
};
