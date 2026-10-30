import React, { forwardRef, useImperativeHandle } from 'react'
// STUB for react-virtuoso: renders every item (no virtualisation).
export const Virtuoso = forwardRef(function Virtuoso({ data = [], itemContent, components = {}, style, className, role, ...rest }, ref) {
  useImperativeHandle(ref, () => ({ scrollToIndex() {} }))
  const Footer = components.Footer
  return <div className={className} style={{ ...style, overflowY: 'auto' }} role={role} aria-label={rest['aria-label']}>
    {data.map((d, i) => <div key={d.id ?? i}>{itemContent(i, d)}</div>)}{Footer ? <Footer /> : null}</div>
})
