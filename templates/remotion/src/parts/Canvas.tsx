// 畫圖用的 SVG 畫布：鋪滿整個畫面，內建發光效果 url(#glow)；圖形、標註、箭頭都畫在這裡面

import React from 'react';
import {useVideoConfig} from 'remotion';

// 發光效果：模糊一份疊在原圖底下；用法 filter="url(#glow)"
export const GlowFilter: React.FC<{id?: string; blur?: number}> = ({id = 'glow', blur = 5}) => (
  <filter id={id}>
    <feGaussianBlur stdDeviation={blur} result="b" />
    <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
  </filter>
);

// 鋪滿畫面的 SVG；defs 放自己的漸層，children 放圖形
export const Canvas: React.FC<{children?: React.ReactNode; defs?: React.ReactNode}> = ({children, defs}) => {
  const {width, height} = useVideoConfig();
  return (
    <svg width={width} height={height} style={{position: 'absolute'}}>
      <defs>
        <GlowFilter />
        {defs}
      </defs>
      {children}
    </svg>
  );
};
