'use strict';
(()=>{const apply=()=>{document.documentElement.dataset.theme='light';document.documentElement.style.colorScheme='light';try{localStorage.setItem('burnwindow-theme','light');}catch{}window.dispatchEvent(new Event('burnwindow-theme'));};window.BurnWindowTheme={set:apply,get:()=> 'light'};apply();})();
