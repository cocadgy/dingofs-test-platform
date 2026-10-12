import {expect,test} from "vitest";
import {cacheMemberOptions} from "./cacheMemberOptions";
test("successful protobuf response without members represents an empty list", () => {
  expect(cacheMemberOptions({id:"q",action:"cache.list",state:"succeeded",result:{steps:[{data:{members:{error:{code:0},result:{info:{cache:{}}}}}}]}})).toEqual([]);
});
test("malformed member arrays remain errors", () => {
  expect(() => cacheMemberOptions({id:"q",action:"cache.list",state:"succeeded",result:{steps:[{data:{members:{result:{members:null}}}}]}})).toThrow();
});
