const f = n => n < 2 ? n : f(n-1) + f(n-2);
const g = x => [...Array(x)].map((_,i) => f(i)).filter(v => v % 2 === 0);
console.log(g(15).reduce((a,b) => a+b, 0));
