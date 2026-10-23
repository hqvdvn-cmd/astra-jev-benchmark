// Functional calibration fixture only. Never used as a benchmark candidate or starter.
import React, { useEffect, useRef, useState } from 'react';
export default function App() {
  const [filter, setFilter] = useState('all'), [year, setYear] = useState(false), [faq, setFaq] = useState([false, false, false]);
  const [modal, setModal] = useState(false), [menu, setMenu] = useState(false), [error, setError] = useState(false), [success, setSuccess] = useState(false);
  const dialog = useRef(null), video = useRef(null);
  useEffect(() => { if (matchMedia('(prefers-reduced-motion: reduce)').matches) video.current.pause(); }, []);
  useEffect(() => {
    if (!modal) return;
    dialog.current.querySelector('button').focus();
    const onKey = e => {
      if (e.key === 'Escape') setModal(false);
      if (e.key === 'Tab') {
        const controls = [...dialog.current.querySelectorAll('button,input,textarea')];
        if (e.shiftKey && document.activeElement === controls[0]) { e.preventDefault(); controls.at(-1).focus(); }
        else if (!e.shiftKey && document.activeElement === controls.at(-1)) { e.preventDefault(); controls[0].focus(); }
      }
    };
    document.addEventListener('keydown', onKey); return () => document.removeEventListener('keydown', onKey);
  }, [modal]);
  const works = [['Afterlight', 'film'], ['Tidal', 'film'], ['Monogram', 'identity'], ['Form & Field', 'identity'], ['Signal', 'interactive'], ['Atlas', 'interactive']];
  return <main style={{ maxWidth: '100%', overflow: 'hidden', padding: 8 }}>
    <h1>Calibration only</h1><button data-testid="menu-toggle" aria-expanded={menu} onClick={() => setMenu(!menu)}>Menu</button>
    {menu && <nav data-testid="mobile-menu">Menu content</nav>}
    <button data-testid="open-brief" onClick={() => { setModal(true); setSuccess(false); }}>Enquire</button>
    <video ref={video} data-testid="hero-video" src="/orbit-loop.mp4" muted autoPlay={!matchMedia('(prefers-reduced-motion: reduce)').matches} loop playsInline width="240" />
    <button data-testid="video-toggle" onClick={() => video.current.paused ? video.current.play() : video.current.pause()}>Play/pause</button>
    <section id="work" data-testid="work">{['all', 'film', 'identity', 'interactive'].map(c => <button key={c} data-testid={'filter-' + c} onClick={() => setFilter(c)}>{c}</button>)}
    {works.filter(([, c]) => filter === 'all' || filter === c).map(([name, c]) => <article key={name} data-testid="project-card" data-category={c}>{name}</article>)}</section>
    <section id="services">Services</section><section id="pricing"><button data-testid="billing-monthly" onClick={() => setYear(false)}>Monthly</button><button data-testid="billing-yearly" onClick={() => setYear(true)}>Yearly</button>
    <p data-testid="price-studio">${year ? '71.20' : '89'}</p><p data-testid="price-team">${year ? '159.20' : '199'}</p></section>
    <section id="faq">{faq.map((open, i) => <div key={i}><button data-testid={'faq-' + i} aria-expanded={open} onClick={() => setFaq(faq.map((value, n) => n === i ? !value : value))}>Question {i + 1}</button>{open && <p data-testid={'faq-answer-' + i}>Answer {i + 1}</p>}</div>)}</section>
    {modal && <div ref={dialog} data-testid="brief-dialog" role="dialog" aria-modal="true" aria-label="Brief" style={{ position: 'fixed', inset: 0, background: 'white', padding: 20 }}>
      <button data-testid="close-brief" onClick={() => setModal(false)}>Close</button><form noValidate onSubmit={e => { e.preventDefault(); const d = new FormData(e.currentTarget); const ok = d.get('name').trim() && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(d.get('email')) && d.get('message').trim(); setError(!ok); setSuccess(!!ok); }}>
      <label>Name<input name="name" data-testid="brief-name" /></label><label>Email<input name="email" data-testid="brief-email" /></label><label>Project brief<textarea name="message" data-testid="brief-message" /></label><button data-testid="submit-brief">Submit</button>
      {error && <p data-testid="brief-errors">Complete the form</p>}{success && <p data-testid="brief-success">Demo request saved locally</p>}</form></div>}
  </main>;
}
