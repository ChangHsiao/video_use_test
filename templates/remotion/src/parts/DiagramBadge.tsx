// 示意圖標籤：灰色細框加灰字，放在標題正下方，提醒觀眾這不是真實畫面（科普短片每段動畫都要有）

import React from 'react';
import {useCurrentFrame} from 'remotion';
import {theme} from '../theme';
import {progress} from './motion';

// 標籤和標題一起淡入；top 預設是標題頂端往下 theme.badge.gap
export const DiagramBadge: React.FC<{text?: string; start?: number; top?: number}> = ({
  text = theme.badge.text, start = 4, top = theme.title.top + theme.badge.gap,
}) => {
  const frame = useCurrentFrame();
  return (
    <div style={{
      position: 'absolute', top, left: '50%', transform: 'translateX(-50%)', whiteSpace: 'nowrap',
      padding: '6px 16px', border: `2px solid ${theme.colors.muted}`, borderRadius: 8,
      fontSize: theme.badge.size, color: theme.colors.line, opacity: progress(frame, start, 14),
    }}>
      {text}
    </div>
  );
};
