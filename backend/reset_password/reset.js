const form=document.getElementById('resetForm');
const error=document.getElementById('error');
const button=document.getElementById('submitButton');
const hash=new URLSearchParams(location.hash.replace(/^#/,''));
const query=new URLSearchParams(location.search);
const accessToken=hash.get('access_token')||query.get('access_token')||'';
if(!accessToken){error.textContent='This recovery link is missing its security token. Request a new reset email.';button.disabled=true}
form.addEventListener('submit',async event=>{
  event.preventDefault();error.textContent='';
  const password=document.getElementById('password').value;
  const confirmation=document.getElementById('confirmPassword').value;
  if(password!==confirmation){error.textContent='Passwords do not match.';return}
  button.disabled=true;
  try{
    const response=await fetch('/auth/reset-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({access_token:accessToken,new_password:password})});
    const body=await response.json();
    if(!response.ok)throw new Error(body.detail||'Password could not be updated.');
    form.classList.add('hidden');document.getElementById('intro').classList.add('hidden');document.getElementById('success').classList.remove('hidden');
    history.replaceState(null,'',location.pathname);
  }catch(problem){error.textContent=problem.message;button.disabled=false}
});
