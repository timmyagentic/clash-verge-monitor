'use strict';
const canvas = document.getElementById('traffic-chart');
if (canvas && window.Chart) {
  const series = JSON.parse(canvas.dataset.series);
  const format = value => {
    const bytes=Number(value); if(bytes>=1073741824)return (bytes/1073741824).toFixed(bytes>=10737418240?0:1)+' GiB';
    if(bytes>=1048576)return (bytes/1048576).toFixed(bytes>=104857600?0:1)+' MiB';
    if(bytes>=1024)return (bytes/1024).toFixed(0)+' KiB'; return bytes+' B';
  };
  const peak=Math.max(0,...series.upload.filter(v=>v!==null),...series.download.filter(v=>v!==null));
  const base=peak>=1073741824?1073741824:peak>=1048576?1048576:peak>=1024?1024:1;
  const rawStep=peak/base/4;
  const step=([.25,.5,1,2,5,10,20,50,100,200,500,1000].find(v=>v>=rawStep)||Math.ceil(rawStep))*base;
  const max=Math.max(step,Math.ceil(peak/step)*step);
  Chart.defaults.font.family='Inter, -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';
  Chart.defaults.color='#7a889d';
  new Chart(canvas, {type:'line',data:{labels:series.labels,datasets:[
    {label:'上传',data:series.upload,borderColor:'#0b8173',backgroundColor:'rgba(20,161,136,.13)',fill:true},
    {label:'下载',data:series.download,borderColor:'#1672ee',backgroundColor:'rgba(22,114,238,.11)',fill:true}
  ]}, options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},
    elements:{line:{borderWidth:2,tension:.25},point:{radius:0,hoverRadius:4,hoverBorderWidth:2,hoverBorderColor:'#fff'}},
    scales:{x:{grid:{color:'#f0f3f6',drawTicks:false},border:{display:false},ticks:{maxTicksLimit:12,maxRotation:0,padding:14,font:{size:11}}},
      y:{beginAtZero:true,max:max,grid:{color:'#edf1f5',drawTicks:false},border:{display:false},ticks:{stepSize:step,maxTicksLimit:5,padding:12,callback:format,font:{size:11}}}},
    plugins:{legend:{display:false},tooltip:{backgroundColor:'#fff',borderColor:'#e2e8ef',borderWidth:1,titleColor:'#526179',bodyColor:'#172334',titleFont:{size:12,weight:'normal'},bodyFont:{size:12},padding:14,cornerRadius:6,boxPadding:6,usePointStyle:true,
      callbacks:{label:c=>' '+c.dataset.label+'  '+format(c.parsed.y)}}}}});
}
document.querySelectorAll('.date-control input').forEach(input=>input.addEventListener('change',()=>input.form.requestSubmit()));

document.querySelectorAll('.state[href="#collection"]').forEach(a=>a.addEventListener('click',()=>{document.getElementById('collection').open=true;}));
