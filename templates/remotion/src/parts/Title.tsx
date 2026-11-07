// 標題區：上面一行灰色小標，下面一行白色大標，大標裡指定的字換成強調色；一起淡入

import React from 'react';
import {useCurrentFrame} from 'remotion';
import {theme} from '../theme';
import {progress} from './motion';

// 把大標拆成「一般字＋強調字＋一般字」，accent 不在大標裡就整行一般字
const splitAccent = (big: string, accent?: string) => {
  const i = accent ? big.indexOf(accent) : -1;
  if (!accent || i < 0) return [big, '', ''];
  return [big.slice(0, i), accent, big.slice(i + accent.length)];
};

// 動畫頂端的標題；start 是開始淡入的格數
export const Title: React.FC<{
  small?: string;
  big: string;
  accent?: string;
  accentColor?: string;
  start?: number;
  top?: number;
}> = ({small, big, accent, accentColor = theme.colors.red, start = 4, top = theme.title.top}) => {
  const frame = useCurrentFrame();
  const p = progress(frame, start, 14);
  const [before, hit, after] = splitAccent(big, accent);
  const t = theme.title;
  return (
    <div style={{position: 'absolute', top, width: '100%', textAlign: 'center', opacity: p}}>
      {small && <div style={{fontSize: t.smallSize, color: theme.colors.subtle}}>{small}</div>}
      <div style={{fontSize: t.bigSize, fontWeight: t.bigWeight, color: theme.colors.text}}>
        {before}<span style={{color: accentColor}}>{hit}</span>{after}
      </div>
    </div>
  );
};
