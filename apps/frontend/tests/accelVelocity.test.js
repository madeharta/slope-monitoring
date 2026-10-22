import test from "node:test";
import assert from "node:assert/strict";
import { estimateAccelVelocity } from "../src/pages/accelVelocity.js";
const data = Array.from({length:100},(_,i)=>({timestamp_utc:new Date(1760000000000+i*10).toISOString(),sample_index:i,adxl355_x_mps2:i<10?0:1,adxl355_y_mps2:0,adxl355_z_mps2:9.81}));
test("steady gravity baseline does not accumulate velocity",()=>{
 const x=estimateAccelVelocity(data.map(r=>({...r,adxl355_x_mps2:0})),"adxl355");
 assert.equal(x.reason,null);assert.ok(x.rows.every(p=>p.vz_mm_s==null||Math.abs(p.vz_mm_s)<1e-7));
});
test("known acceleration integrates in valid interval",()=>{
 const x=estimateAccelVelocity(data,"adxl355");assert.ok(Math.abs(x.rows.at(-1).vx_mm_s-895)<1);
});
test("downsample rejected",()=>assert.match(estimateAccelVelocity(data,"adxl355",{downsampling:{method:"deterministic_stride",stride:2}}).reason,/Full-resolution/));
test("timestamp glitch splits segments instead of hiding entire graph",()=>{
 const b=data.map(r=>({...r}));b[40].timestamp_utc=b[39].timestamp_utc;
 const x=estimateAccelVelocity(b,"adxl355");assert.equal(x.reason,null);
 assert.equal(x.valid_segments,2);assert.ok(x.rows.some(r=>r.vx_mm_s===null));
});
test("index gap never bridged",()=>{
 const b=data.map(r=>({...r}));b[40].sample_index=900;
 const x=estimateAccelVelocity(b,"adxl355");assert.equal(x.reason,null);assert.ok(x.gaps>=2);
});
test("microsecond ISO timestamp precision preserved",()=>{
 const b=data.map((r,i)=>({...r,timestamp_utc:`2026-10-22T07:00:00.${String(i*500).padStart(6,"0")}Z`}));
 const x=estimateAccelVelocity(b,"adxl355");assert.equal(x.reason,null);
});
test("all duplicates remain blocked",()=>{
 const b=data.map(r=>({...r,timestamp_utc:data[0].timestamp_utc}));
 assert.match(estimateAccelVelocity(b,"adxl355").reason,/No verifiable/);
});
