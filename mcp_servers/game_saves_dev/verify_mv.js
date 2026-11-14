// usage: node verify_mv.js <lz-string.js> <save> <backup>  -> prints gold, its type, and every other changed path
const fs=require('fs'),vm=require('vm');const c={};vm.createContext(c);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8')+';this.LZString=LZString;',c);
const dec=p=>JSON.parse(c.LZString.decompressFromBase64(fs.readFileSync(p,'utf8')));
const a=dec(process.argv[3]), b=dec(process.argv[4]);
const diffs=[];(function walk(x,y,p){ if(x===null||typeof x!=='object'){ if(x!==y) diffs.push(p+': '+JSON.stringify(y)+' -> '+JSON.stringify(x)); return;}
 for(const k of new Set([...Object.keys(x),...Object.keys(y||{})])) walk(x[k],(y||{})[k],p+'.'+k); })(a,b,'');
console.log(`gold=${a.party._gold} (${typeof a.party._gold}) diffs=${JSON.stringify(diffs)}`);
