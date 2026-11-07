// 標註：在圖形上點一個小圓點，引線長到文字的位置，文字再淡入；用來說「這是什麼」

import React from 'react';
import {useCurrentFrame} from 'remotion';
import {theme} from '../theme';
import {progress} from './motion';

// (x, y) 是被標註的點，(tx, ty) 是引線終點；文字放在終點外側（終點在下方就寫在線下，否則寫在線上）
export const Callout: React.FC<{
  x: number; y: number; tx: number; ty: number;
  text: string; color?: string; start: number; fontSize?: number;
}> = ({x, y, tx, ty, text, color = theme.colors.text, start, fontSize = 56}) => {
  const frame = useCurrentFrame();
  const line = progress(frame, start, 10);
  const txt = progress(frame, start + 6, 10);
  const textY = ty > y ? ty + fontSize * 0.9 : ty - 14;
  return (
    <g style={{paintOrder: 'stroke'}}>
      <circle cx={x} cy={y} r={8 * line} fill={color} />
      <line x1={x} y1={y} x2={x + (tx - x) * line} y2={y + (ty - y) * line} stroke={color} strokeWidth={3} opacity={0.8} />
      <text x={tx} y={textY} fill={color} fontSize={fontSize} fontWeight={900} textAnchor="middle"
        stroke={theme.colors.outline} strokeWidth={10} opacity={txt}>{text}</text>
    </g>
  );
};
