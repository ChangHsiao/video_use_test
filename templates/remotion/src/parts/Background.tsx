// 背景：由中間往外的暗色漸層，加上細格線；放在每段動畫的最底層

import React from 'react';
import {AbsoluteFill} from 'remotion';
import {theme} from '../theme';

// 整個畫面的底，children 疊在上面
export const Background: React.FC<{children?: React.ReactNode; grid?: boolean}> = ({children, grid = true}) => {
  const b = theme.background;
  return (
    <AbsoluteFill style={{fontFamily: theme.font, background: `radial-gradient(ellipse at 50% 45%, ${b.inner} 0%, ${b.outer} 70%)`}}>
      {grid && (
        <AbsoluteFill style={{
          backgroundImage: `linear-gradient(${b.grid} 1px, transparent 1px), linear-gradient(90deg, ${b.grid} 1px, transparent 1px)`,
          backgroundSize: `${b.gridSize}px ${b.gridSize}px`,
        }} />
      )}
      {children}
    </AbsoluteFill>
  );
};
