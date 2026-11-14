// usage: node verify_mz.js <pako.min.js> <save> <backup>; decodes the way rmmz_managers.js StorageManager does
const fs=require('fs'),vm=require('vm');const c={window:{}};c.self=c.window;vm.createContext(c);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8')+';this.P=(typeof pako!=="undefined"?pako:window.pako);',c);
const dec=p=>JSON.parse(c.P.inflate(fs.readFileSync(p,{encoding:'utf8'}),{to:'string'}));
const a=dec(process.argv[3]), b=dec(process.argv[4]);
const diffs=[];(function walk(x,y,p){ if(x===null||typeof x!=='object'){ if(x!==y) diffs.push(p+': '+JSON.stringify(y)+' -> '+JSON.stringify(x)); return;}
 for(const k of new Set([...Object.keys(x),...Object.keys(y||{})])) walk(x[k],(y||{})[k],p+'.'+k); })(a,b,'');
console.log(`gold=${a.party._gold} (${typeof a.party._gold}) diffs=${JSON.stringify(diffs)}`);
