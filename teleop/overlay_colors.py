"""Read actual SVG fill/clip state; movement alone is not yellow highlighting."""
YELLOW_SNAPSHOT = """() => {
 const groups={};
 for (const e of document.querySelectorAll('#overlayRoot [data-side][data-role]')) {
   const key=e.dataset.side+':'+e.dataset.role, s=getComputedStyle(e), r=e.getBoundingClientRect();
   const rgb=s.fill.match(/rgba?\\(([^)]+)\\)/)?.[1].split(',').map(Number);
   let clipArea=1;
   const clip=e.getAttribute('clip-path');
   if(clip) {
     const rect=document.getElementById(clip.slice(5,-1))?.firstElementChild;
     if(rect?.tagName==='rect')clipArea=Number(rect.getAttribute('width'))*Number(rect.getAttribute('height'));
   }
   const yellow=Boolean(rgb && rgb[0]>=180 && rgb[1]>=130 && rgb[2]<=100 &&
     (rgb.length<4||rgb[3]>0) && Number(s.opacity)>0 && Number(s.fillOpacity)>0 &&
     s.visibility!=='hidden' && s.display!=='none' && clipArea>0 && r.width>0 && r.height>0);
   (groups[key]??=[]).push({tag:e.tagName,classes:e.getAttribute('class'),fill:s.fill,
     fillOpacity:s.fillOpacity,opacity:s.opacity,clip,clipArea,rect:[r.x,r.y,r.width,r.height],yellow});
 }
 return groups;
}"""


def yellow_components(snapshot):
    return {name for name,elements in snapshot.items() if any(e['yellow'] for e in elements)}


def color_verdict(snapshot, expected):
    yellow=yellow_components(snapshot)
    return {'yellow_components':sorted(yellow),'target_yellow':bool(yellow&expected) if expected else not yellow,
            'unexpected_yellow_components':sorted(yellow-expected),
            'passed':bool(yellow&expected) and not yellow-expected if expected else not yellow}
