import { afterEach, describe, expect, it, vi } from 'vitest';
import { detectConflicts, generateRoutines, loadSections, overview } from './localData';

const section = (course_code:string, day:string, start:number, end:number, faculty='Instructor'): any => ({id:1,source_serial:1,source_page:1,program:'BSCSE',course_code,course_name:course_code,section:'A',section_note:'',faculty,faculty_initial:'I',credits:3,meetings:[{day,start,end,room:'R'}],source_fields:{}});
describe('browser schedule engine',()=>{
 afterEach(()=>vi.unstubAllGlobals());
 it('reports overlaps while allowing meetings that only touch',()=>{
  const a=section('CSE 1001','Sun',540,600),b=section('MAT 1001','sun',599,650),c=section('PHY 1001','Sun',650,700);
  expect(detectConflicts([a,b,c])).toEqual([{first:'CSE 1001 A',second:'MAT 1001 A',day:'Sun',start:599,end:600}]);
 });
 it('uses the bundled catalog and reports its real record totals',async()=>{
  const original=globalThis.fetch;
  vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({sections:[
   {...section('CSE 1115','Tue',540,600,'Second Choice'),source_serial:1},
   {...section('CSE 1115','Wed',540,600,'First Choice'),source_serial:2},
   {...section('MAT 1001','Mon',540,600,'Math Faculty'),source_serial:3},
  ]}),{status:200,headers:{'Content-Type':'application/json'}})));
  try {
   const summary=await overview();expect(summary.sections).toBe(3);
   const routines=await generateRoutines({course_selections:[{program:'BSCSE',course_code:'CSE 1115'}],faculty_preferences:{'BSCSE:CSE 1115':['First Choice']},limit:4,monday_preference:'any'});
   expect(routines[0].sections?.[0].faculty).toBe('First Choice');
   await expect(generateRoutines({course_selections:[{program:'BSCSE',course_code:'MAT 1001'}],faculty_preferences:{},monday_preference:'avoid'})).rejects.toThrow('without Monday classes');
  } finally { vi.stubGlobal('fetch',original); }
 });
});
