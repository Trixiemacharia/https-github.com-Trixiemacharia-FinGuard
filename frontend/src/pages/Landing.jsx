import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowDown, ArrowRight, ArrowUpRight, Check, ChevronDown, Globe2, ShieldCheck, WalletCards, Sparkles, ChartNoAxesCombined, PiggyBank, LockKeyhole } from 'lucide-react';

const copy = {
  en: {
    nav: 'Get started', eyebrow: 'A clearer relationship with money', title: 'Your money,\nwith more meaning.', intro: 'A personal wallet for confident everyday payments and a better view of your financial life.', cta: 'Get started', secure: 'Designed around your security', features: 'A wallet that works harder for you', featureIntro: 'One connected place for the everyday decisions that shape your financial wellbeing.', heroLabel: 'YOUR FINANCIAL LIFE', heroLine: 'Clear. Connected. Yours.', income: 'Income', spending: 'Spending', howKicker: 'GET STARTED WITH CONFIDENCE', howIntro: 'Every step is clear, secure and designed to help you get started.', phone: 'Phone number', email: 'Email address', photoLabel: 'Photograph', signIn: 'Sign in', seeFeatures: 'See wallet features',
    cards: [
      ['Smart Financial Management', 'Monitor income, expenses, budgets and everyday activity in one clear view.', 'photo-1554224155-6726b3ff858f'],
      ['Intelligent Financial Assistant', 'Ask practical money questions and get guidance grounded in your account data.', 'photo-1454165804606-c3d57bc86b40'],
      ['Secure Digital Payments', 'Send and receive money with protected transfers and M-Pesa support.', 'photo-1556742049-0cfed4f6a45d'],
      ['Savings and Financial Goals', 'Set a goal, add contributions and follow your progress over time.', 'photo-1518458028785-8fbcd101ebb9'],
      ['Financial Intelligence', 'Understand your spending patterns and see a thoughtful cash-flow outlook.', 'photo-1460925895917-afdab827c52f'],
      ['Account Security', 'Keep your wallet protected with transaction monitoring and security controls.', 'photo-1563013544-824ae1b704d3'],
    ],
    stepsTitle: 'HOW IT WORKS', steps: [
      ['STEP 01', 'CREATE AN ACCOUNT', 'Create your personal wallet account using your email and password.'],
      ['STEP 02', 'VERIFY YOUR IDENTITY', 'Confirm your phone number, verify your email address and upload a photograph.'],
      ['STEP 03', 'PERSONAL DETAILS', 'Tell us where you live, your occupation and your monthly earnings.'],
      ['STEP 04', 'YOUR ACCOUNT', 'Review and submit your application. After account checks and approval, start using your wallet.'],
    ], footer: 'A more considered way to manage your money.'
  },
  sw: {
    nav: 'Anza sasa', eyebrow: 'Uhusiano bora na pesa zako', title: 'Pesa zako,\nkwa uwazi zaidi.', intro: 'Pochi binafsi ya malipo ya kila siku kwa kujiamini na kuelewa vizuri hali yako ya kifedha.', cta: 'Anza sasa', secure: 'Usalama wako ni muhimu', features: 'Pochi inayokusaidia zaidi', featureIntro: 'Mahali pamoja pa kufanya maamuzi ya kila siku yanayoboresha hali yako ya kifedha.', heroLabel: 'MAISHA YAKO YA KIFEDHA', heroLine: 'Wazi. Pamoja. Yako.', income: 'Mapato', spending: 'Matumizi', howKicker: 'ANZA KWA KUJIAMINI', howIntro: 'Kila hatua iko wazi na salama, na imeundwa kukusaidia kuanza.', phone: 'Nambari ya simu', email: 'Barua pepe', photoLabel: 'Picha', signIn: 'Ingia', seeFeatures: 'Tazama huduma za pochi',
    cards: [
      ['Usimamizi Mahiri wa Fedha', 'Fuatilia mapato, matumizi, bajeti na shughuli zako za kila siku kwa urahisi.', 'photo-1554224155-6726b3ff858f'],
      ['Msaidizi Mahiri wa Fedha', 'Uliza maswali ya kifedha na upokee ushauri unaotegemea taarifa za akaunti yako.', 'photo-1454165804606-c3d57bc86b40'],
      ['Malipo Salama ya Kidijitali', 'Tuma na pokea pesa kupitia malipo salama na huduma ya M-Pesa.', 'photo-1556742049-0cfed4f6a45d'],
      ['Akiba na Malengo ya Fedha', 'Weka lengo la akiba, ongeza michango na ufuatilie maendeleo yako.', 'photo-1518458028785-8fbcd101ebb9'],
      ['Taarifa za Kifedha', 'Elewa matumizi yako na utazame makadirio ya mtiririko wa fedha.', 'photo-1460925895917-afdab827c52f'],
      ['Usalama wa Akaunti', 'Linda pochi yako kwa ufuatiliaji wa miamala na vidhibiti vya usalama.', 'photo-1563013544-824ae1b704d3'],
    ],
    stepsTitle: 'HOW IT WORKS', steps: [
      ['HATUA 01', 'FUNGUA AKAUNTI', 'Fungua akaunti yako ya pochi kwa kutumia barua pepe na nenosiri.'],
      ['HATUA 02', 'THIBITISHA UTAMBULISHO', 'Thibitisha nambari ya simu, barua pepe na upakie picha yako.'],
      ['HATUA 03', 'TAARIFA BINAFSI', 'Tuambie unapoishi, kazi yako na mapato yako ya kila mwezi.'],
      ['HATUA 04', 'AKAUNTI YAKO', 'Kagua na utume ombi lako. Baada ya ukaguzi na idhini, anza kutumia pochi yako.'],
    ], footer: 'Njia makini zaidi ya kusimamia pesa zako.'
  }
};

const photo = (id) => `https://images.unsplash.com/${id}?auto=format&fit=crop&w=1400&q=85`;

export function Landing() {
  const [language, setLanguage] = useState(() => localStorage.getItem('finguard-language') || 'en');
  const [languageOpen, setLanguageOpen] = useState(false);
  const t = copy[language];
  const selectLanguage = (value) => { setLanguage(value); localStorage.setItem('finguard-language', value); setLanguageOpen(false); };
  return <main className="landing-page" lang={language === 'sw' ? 'sw' : 'en'}>
    <header className="landing-nav"><Link className="landing-brand" to="/"><span className="landing-mark"><ShieldCheck size={20}/></span>fin<span>guard</span></Link><div className="landing-actions">
      <div className="language-wrap"><button className="language-button" onClick={() => setLanguageOpen(!languageOpen)} aria-expanded={languageOpen}><Globe2 size={17}/>{language === 'en' ? 'English' : 'Kiswahili'}<ChevronDown size={14}/></button>{languageOpen && <div className="language-menu"><button onClick={() => selectLanguage('en')}>English {language === 'en' && <Check size={14}/>}</button><button onClick={() => selectLanguage('sw')}>Kiswahili {language === 'sw' && <Check size={14}/>}</button></div>}</div>
      <Link className="landing-cta" to="/auth?mode=register">{t.nav}<ArrowRight size={16}/></Link>
    </div></header>
    <section className="landing-hero" style={{ backgroundImage: `linear-gradient(90deg,rgba(11,34,54,.9) 0%,rgba(11,34,54,.68) 43%,rgba(11,34,54,.08) 100%),url(${photo('photo-1556740758-90de374c12ad')})` }}>
      <div className="hero-copy"><span className="hero-kicker"><Sparkles size={14}/>{t.eyebrow}</span><h1>{t.title.split('\n').map((line) => <span key={line}>{line}<br/></span>)}</h1><p>{t.intro}</p><Link className="hero-button" to="/auth?mode=register">{t.cta}<ArrowUpRight size={17}/></Link><div className="hero-trust"><LockKeyhole size={14}/>{t.secure}</div></div>
      <div className="hero-card"><span className="hero-card-icon"><WalletCards size={17}/></span><small>{t.heroLabel}</small><strong>{t.heroLine}</strong><div className="hero-card-line"><span><ArrowDown size={13}/> {t.income}</span><span><ArrowUpRight size={13}/> {t.spending}</span></div></div>
      <a href="#features" className="hero-scroll" aria-label={t.seeFeatures}><ArrowDown size={17}/></a>
    </section>
    <section className="features-section" id="features"><div className="landing-section-head"><span>{language === 'en' ? 'FINGUARD WALLET' : 'POCHI YA FINGUARD'}</span><h2>{t.features}</h2><p>{t.featureIntro}</p></div><div className="feature-grid">{t.cards.map(([title, description, image], index) => <article className="feature-card" key={title}><div className="feature-image" style={{ backgroundImage: `url(${photo(image)})` }}><span>0{index + 1}</span></div><div className="feature-content"><span className="feature-icon">{[<ChartNoAxesCombined/>,<Sparkles/>,<WalletCards/>,<PiggyBank/>,<ChartNoAxesCombined/>,<ShieldCheck/>][index]}</span><h3>{title}</h3><p>{description}</p><ArrowUpRight className="feature-arrow" size={17}/></div></article>)}</div></section>
    <section className="how-section"><div className="how-heading"><span>{t.howKicker}</span><h2>{t.stepsTitle}</h2><p>{t.howIntro}</p></div><div className="steps-grid">{t.steps.map(([step, title, body], index) => <article className="how-step" key={step}><div className="step-top"><span className="step-number">{step.slice(-2)}</span>{index < 3 && <span className="step-line"/>}</div><span className="step-label">{step}</span><h3>{title}</h3><p>{body}</p>{index === 1 && <ul className="verification-list"><li><Check size={13}/>{t.phone}</li><li><Check size={13}/>{t.email}</li><li><Check size={13}/>{t.photoLabel}</li></ul>}</article>)}</div></section>
    <footer className="landing-footer"><Link className="landing-brand" to="/"><span className="landing-mark"><ShieldCheck size={18}/></span>fin<span>guard</span></Link><span>{t.footer}</span><Link to="/auth?mode=login">{t.signIn} <ArrowRight size={14}/></Link></footer>
  </main>;
}
