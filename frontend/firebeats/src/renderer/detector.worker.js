self.onmessage = async (e)=>{
  const { endpoint, cameraId, bytes } = e.data;
  try{
    const resp = await fetch(endpoint, { method:'POST', headers:{ 'Content-Type':'application/octet-stream','camera-id': cameraId }, body: bytes });
    const data = resp.ok ? await resp.json() : { boxes: [] };
    self.postMessage({ boxes: data.boxes||[] });
  }catch(err){ self.postMessage({ boxes: [] }); }
};