import {render,screen,fireEvent,cleanup} from "@testing-library/react";
import {afterEach,it,expect,vi} from "vitest";
import {ProfileComparison} from "../components/ProfileComparison";
import type {MapProfileComparison,MeasurementRecord} from "../types";
afterEach(cleanup);
const samples=[0,1,2].map((value,index)=>({distance_km:index,lon:116+index,lat:40,value:index===1?null:value}));
const result={total_distance_km:2,paired_valid_count:2,interpretation_note:"相关性不代表因果",population:{kind:"population",samples,unit:"人/km²",source_name:"GPW",source_year:2020,no_data_count:1},terrain:{kind:"terrain",samples:samples.map(p=>({...p,value:100})),unit:"米",source_name:"Mapzen",source_year:null,no_data_count:0}} as MapProfileComparison;
it("uses distinct units and breaks missing segments without filling zeros",()=>{const {container}=render(<ProfileComparison record={{name:"北京—上海"} as MeasurementRecord} result={result} onHover={()=>{}} onClose={()=>{}}/>);expect(screen.getByText("● 人口密度（人/km²）")).toBeVisible();expect(screen.getByText("● 高程（米）")).toBeVisible();const paths=container.querySelectorAll("svg g path");expect(paths[0].getAttribute("d")?.match(/M/g)).toHaveLength(2);expect(paths[0].getAttribute("d")).not.toContain("L");expect(paths[1].getAttribute("d")?.match(/L/g)).toHaveLength(2);});
it("clears map hover on leaving the graph",()=>{const hover=vi.fn();render(<ProfileComparison record={{name:"测线"} as MeasurementRecord} result={result} onHover={hover} onClose={()=>{}}/>);fireEvent.pointerLeave(screen.getByRole("img"));expect(hover).toHaveBeenCalledWith(null);});
