"use client";

import React, { useState, useEffect } from "react";
import { 
  Plus, 
  Users, 
  Activity, 
  CheckCircle, 
  Clock, 
  AlertTriangle, 
  Phone, 
  Send, 
  Upload, 
  UserPlus, 
  Volume2, 
  Sparkles,
  Info,
  Calendar,
  Languages,
  Eye,
  Check,
  RefreshCw
} from "lucide-react";

export default function Dashboard() {
  const [patients, setPatients] = useState([]);
  const [reminders, setReminders] = useState([]);
  const [summary, setSummary] = useState({ total_patients: 0, taken: 0, pending: 0, missed: 0 });
  const [recentLogs, setRecentLogs] = useState([]);
  
  // Simulator states
  const [activeCalls, setActiveCalls] = useState([]);
  const [whatsappAlerts, setWhatsappAlerts] = useState([]);
  const [triggeringId, setTriggeringId] = useState(null);
  
  // Create Patient Form
  const [newPatient, setNewPatient] = useState({
    name: "",
    phone: "",
    language: "English",
    caregiver_whatsapp: "",
    greeting_audio_url: ""
  });
  
  // Create Medicine Form
  const [newMedicine, setNewMedicine] = useState({
    elderly_id: "",
    name: "",
    dosage: "1 pill",
    frequency: "Daily",
    time: "08:00",
    duration: "30 Days",
    description: ""
  });

  // OCR Simulator states
  const [ocrLoading, setOcrLoading] = useState(false);
  const [ocrResult, setOcrResult] = useState(null);
  const [ocrTargetPatientId, setOcrTargetPatientId] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);

  const backendUrl = "http://localhost:8000";

  // Fetch all initial data — each call is independent so one failure doesn't block the rest
  const fetchData = async () => {
    // Patients
    try {
      const patientsRes = await fetch(`${backendUrl}/api/elderly`);
      const patientsData = await patientsRes.json();
      setPatients(patientsData);
    } catch (err) { console.error("Failed to fetch patients:", err); }

    // Reminders
    try {
      const remindersRes = await fetch(`${backendUrl}/api/reminders`);
      const remindersData = await remindersRes.json();
      // Only show reminders from the last 24 hours so old completed ones don't clutter
      const cutoff = new Date(Date.now() - 24 * 60 * 60 * 1000);
      const recent = remindersData.filter(r => new Date(r.scheduled_time) >= cutoff);
      setReminders(recent);
    } catch (err) { console.error("Failed to fetch reminders:", err); }

    // Summary & Logs
    try {
      const dashRes = await fetch(`${backendUrl}/api/dashboard`);
      const dashData = await dashRes.json();
      setSummary(dashData.summary);
      setRecentLogs(dashData.recent_logs);
    } catch (err) { console.error("Failed to fetch dashboard:", err); }

    // Simulator Active Calls
    try {
      const callsRes = await fetch(`${backendUrl}/api/simulator/calls`);
      const callsData = await callsRes.json();
      setActiveCalls(callsData);
    } catch (err) { console.error("Failed to fetch simulator calls:", err); }

    // Simulator WhatsApp alerts
    try {
      const whatsappRes = await fetch(`${backendUrl}/api/simulator/whatsapp`);
      const whatsappData = await whatsappRes.json();
      setWhatsappAlerts(whatsappData);
    } catch (err) { console.error("Failed to fetch whatsapp alerts:", err); }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 3000); // Poll every 3 seconds for real-time simulator behavior
    return () => clearInterval(interval);
  }, []);

  // Handlers
  const handleAddPatient = async (e) => {
    e.preventDefault();
    if (!newPatient.name || !newPatient.phone || !newPatient.caregiver_whatsapp) return;
    try {
      const res = await fetch(`${backendUrl}/api/elderly`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newPatient)
      });
      if (res.ok) {
        setNewPatient({ name: "", phone: "", language: "English", caregiver_whatsapp: "", greeting_audio_url: "" });
        fetchData();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleAddMedicine = async (e) => {
    e.preventDefault();
    if (!newMedicine.elderly_id || !newMedicine.name || !newMedicine.description) return;
    try {
      const res = await fetch(`${backendUrl}/api/elderly/${newMedicine.elderly_id}/medicines`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newMedicine)
      });
      if (res.ok) {
        setNewMedicine({ elderly_id: "", name: "", dosage: "1 pill", frequency: "Daily", time: "08:00", duration: "30 Days", description: "" });
        fetchData();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleTriggerReminder = async (jobId) => {
    setTriggeringId(jobId);
    try {
      await fetch(`${backendUrl}/api/reminders/${jobId}/trigger`, { method: "POST" });
      await fetchData();
    } catch (err) {
      console.error(err);
    } finally {
      setTriggeringId(null);
    }
  };

  const handleSimulatorAction = async (jobId, action) => {
    try {
      await fetch(`${backendUrl}/api/simulator/calls/${jobId}/action?action=${action}`, { method: "POST" });
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  // Real OCR Upload handler
  const handleRealOCRUpload = async (e) => {
    e.preventDefault();
    if (!selectedFile) {
      alert("Please select a prescription image/PDF file to upload first.");
      return;
    }
    setOcrLoading(true);
    setOcrResult(null);

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
      const res = await fetch(`${backendUrl}/api/ocr-parser`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || "Failed to parse the prescription.");
      }

      const data = await res.json();
      setOcrResult(data.medicines || []);
    } catch (err) {
      console.error("OCR upload error:", err);
      alert(err.message || "An error occurred while uploading/parsing the prescription.");
    } finally {
      setOcrLoading(false);
    }
  };

  const handleFillOcrMedicine = (medData, idx) => {
    if (!ocrTargetPatientId) {
      alert("Please select a target patient profile in the OCR panel first.");
      return;
    }
    setNewMedicine({
      elderly_id: ocrTargetPatientId,
      name: medData.name || "",
      dosage: medData.dosage || "1 pill",
      frequency: medData.frequency || "Daily",
      time: medData.time || "08:00",
      duration: medData.duration || "30 Days",
      description: medData.description || ""
    });

    // Remove the specific imported medicine from the parsed results using its index
    setOcrResult(prev => prev.filter((_, i) => i !== idx));

    // Scroll to the Schedule Medication form smoothly
    const formElement = document.getElementById("schedule-medication-form");
    if (formElement) {
      formElement.scrollIntoView({ behavior: "smooth" });
    }
  };

  return (
    <div className="max-w-7xl mx-auto p-4 md:p-8 space-y-8">
      {/* Header Banner */}
      <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-white/10 pb-6">
        <div>
          <div className="flex items-center gap-2 text-indigo-400 font-semibold mb-1 text-sm tracking-wider uppercase">
            <Sparkles className="w-4 h-4" /> Live Patient Adherence Portal
          </div>
          <h1 className="text-4xl font-extrabold tracking-tight bg-gradient-to-r from-white via-indigo-200 to-indigo-400 bg-clip-text text-transparent">
            LastMile Meds
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Voice reminders for elderly patients. WhatsApp alerts & escalation for caregivers.
          </p>
        </div>
        <div className="flex gap-3">
          <button 
            onClick={fetchData}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600/20 border border-indigo-500/30 text-indigo-300 hover:bg-indigo-600/40 rounded-lg text-sm transition-all"
          >
            <RefreshCw className="w-4 h-4" /> Force Sync
          </button>
        </div>
      </header>

      {/* Summary Cards */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="glass-panel p-6 flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Total Elderly Patients</span>
            <h3 className="text-3xl font-extrabold text-white mt-1">{summary.total_patients}</h3>
          </div>
          <div className="p-3 bg-indigo-500/10 text-indigo-400 rounded-xl">
            <Users className="w-6 h-6" />
          </div>
        </div>

        <div className="glass-panel p-6 flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Taken (Confirmed)</span>
            <h3 className="text-3xl font-extrabold text-emerald-400 mt-1">{summary.taken}</h3>
          </div>
          <div className="p-3 bg-emerald-500/10 text-emerald-400 rounded-xl">
            <CheckCircle className="w-6 h-6" />
          </div>
        </div>

        <div className="glass-panel p-6 flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Pending Calls</span>
            <h3 className="text-3xl font-extrabold text-amber-400 mt-1">{summary.pending}</h3>
          </div>
          <div className="p-3 bg-amber-500/10 text-amber-400 rounded-xl">
            <Clock className="w-6 h-6" />
          </div>
        </div>

        <div className="glass-panel p-6 flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Missed Escalated</span>
            <h3 className="text-3xl font-extrabold text-rose-400 mt-1">{summary.missed}</h3>
          </div>
          <div className="p-3 bg-rose-500/10 text-rose-400 rounded-xl">
            <AlertTriangle className="w-6 h-6" />
          </div>
        </div>
      </section>

      {/* Main Grid: Portal controls, Simulators */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        {/* Left Side: Setup Forms, Medicine Logs, Patient lists (8 cols) */}
        <main className="lg:col-span-8 space-y-8">
          
          {/* Patients & Medicines Registry */}
          <div className="glass-panel p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold flex items-center gap-2 text-white">
                <Users className="w-5 h-5 text-indigo-400" /> Patient Registry
              </h2>
            </div>
            
            {patients.length === 0 ? (
              <div className="text-center py-8 text-slate-500 border border-white/5 border-dashed rounded-xl">
                No patients registered yet. Add one below to start scheduling.
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {patients.map(p => (
                  <div key={p.id} className="p-4 bg-white/5 border border-white/5 rounded-xl flex flex-col justify-between">
                    <div>
                      <div className="flex items-center justify-between">
                        <h4 className="font-semibold text-white text-base">{p.name}</h4>
                        <span className="text-xs px-2.5 py-1 bg-indigo-500/20 text-indigo-300 rounded-full font-medium flex items-center gap-1">
                          <Languages className="w-3 h-3" /> {p.language}
                        </span>
                      </div>
                      <p className="text-xs text-slate-400 mt-2">📞 Call Phone: {p.phone}</p>
                      <p className="text-xs text-slate-400 mt-1">💬 Caregiver WA: {p.caregiver_whatsapp}</p>
                      {p.greeting_audio_url && (
                        <p className="text-xs text-indigo-300 mt-2 flex items-center gap-1">
                          <Volume2 className="w-3.5 h-3.5" /> Greeting message active
                        </p>
                      )}
                    </div>
                    <div className="mt-4 pt-3 border-t border-white/5">
                      <span className="text-xs font-semibold text-slate-400 block mb-2">Active Medications:</span>
                      {p.medicines && p.medicines.length > 0 ? (
                        <div className="flex flex-wrap gap-1.5">
                          {p.medicines.map(m => (
                            <span key={m.id} className="text-[11px] px-2 py-0.5 bg-white/10 text-slate-200 rounded">
                              {m.name} ({m.time})
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-xs text-slate-500 italic">No medications scheduled.</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Scheduled Reminders Status (Active logs) */}
          <div className="glass-panel p-6">
            <h2 className="text-xl font-bold flex items-center gap-2 mb-6 text-white">
              <Clock className="w-5 h-5 text-amber-400" /> Scheduled Reminders & State Machine
            </h2>
            
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-white/10 text-xs font-semibold text-slate-400 uppercase">
                    <th className="py-3 px-4">Patient</th>
                    <th className="py-3 px-4">Medicine & Dosage</th>
                    <th className="py-3 px-4">Scheduled Time</th>
                    <th className="py-3 px-4">Attempts</th>
                    <th className="py-3 px-4">State / Status</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5 text-sm">
                  {reminders.length === 0 ? (
                    <tr>
                      <td colSpan="6" className="text-center py-6 text-slate-500">No reminders scheduled in the last 24 hours. Add a medicine above to schedule one.</td>
                    </tr>
                  ) : (
                    reminders.map(r => {
                      let statusBadge = "bg-slate-500/20 text-slate-400";
                      if (r.status === "CONFIRMED") statusBadge = "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30";
                      else if (r.status === "CALLING") statusBadge = "bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 animate-pulse";
                      else if (r.status === "WAITING_CONFIRMATION") statusBadge = "bg-amber-500/20 text-amber-400 border border-amber-500/30";
                      else if (r.status === "RETRYING") statusBadge = "bg-blue-500/20 text-blue-300 border border-blue-500/30";
                      else if (r.status === "FAILED") statusBadge = "bg-rose-500/20 text-rose-400 border border-rose-500/30";
                      else if (r.status === "CAREGIVER_NOTIFIED") statusBadge = "bg-red-600/30 text-rose-300 border border-red-500/30";

                      return (
                        <tr key={r.id} className="hover:bg-white/5 transition-colors">
                          <td className="py-3.5 px-4 font-medium text-white">{r.elderly?.name}</td>
                          <td className="py-3.5 px-4">
                            <div className="font-semibold text-slate-200">{r.medicine?.name}</div>
                            <div className="text-xs text-indigo-300">{r.medicine?.dosage}</div>
                          </td>
                          <td className="py-3.5 px-4 text-slate-300">
                            {new Date(r.scheduled_time).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                          </td>
                          <td className="py-3.5 px-4 text-slate-300 font-mono">{r.attempt_count}/3</td>
                          <td className="py-3.5 px-4">
                            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${statusBadge}`}>
                              {r.status}
                            </span>
                          </td>
                          <td className="py-3.5 px-4 text-right">
                            {r.status !== "CONFIRMED" && r.status !== "CAREGIVER_NOTIFIED" && (
                              <button 
                                onClick={() => handleTriggerReminder(r.id)}
                                disabled={triggeringId === r.id}
                                className="px-3 py-1 bg-indigo-600 text-white rounded text-xs font-medium hover:bg-indigo-700 disabled:bg-indigo-600/50 transition-colors inline-flex items-center gap-1"
                              >
                                {triggeringId === r.id ? (
                                  <><RefreshCw className="w-3 h-3 animate-spin" /> Calling...</>
                                ) : (
                                  <><Phone className="w-3 h-3" /> Trigger Call</>
                                )}
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Form Controls Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            
            {/* Add Patient Card */}
            <div className="glass-panel p-6">
              <h3 className="text-lg font-bold flex items-center gap-2 mb-4 text-white">
                <UserPlus className="w-5 h-5 text-indigo-400" /> Add Elderly Patient
              </h3>
              <form onSubmit={handleAddPatient} className="space-y-4">
                <div className="flex flex-col">
                  <label className="text-xs font-semibold text-slate-400 mb-1">Full Name</label>
                  <input 
                    type="text" 
                    placeholder="e.g. Grandma Saraswathi" 
                    value={newPatient.name} 
                    onChange={e => setNewPatient({...newPatient, name: e.target.value})}
                    className="glass-input"
                  />
                </div>
                <div className="flex flex-col">
                  <label className="text-xs font-semibold text-slate-400 mb-1">Mobile Phone (Twilio Target)</label>
                  <input 
                    type="text" 
                    placeholder="e.g. +91 9876543210" 
                    value={newPatient.phone} 
                    onChange={e => setNewPatient({...newPatient, phone: e.target.value})}
                    className="glass-input"
                  />
                </div>
                <div className="flex flex-col">
                  <label className="text-xs font-semibold text-slate-400 mb-1">Language</label>
                  <select 
                    value={newPatient.language} 
                    onChange={e => setNewPatient({...newPatient, language: e.target.value})}
                    className="glass-input bg-slate-900 border-white/10 text-white"
                  >
                    <option className="bg-slate-900 text-white" value="English">English</option>
                    <option className="bg-slate-900 text-white" value="Hindi">Hindi (हिंदी)</option>
                    <option className="bg-slate-900 text-white" value="Kannada">Kannada (ಕನ್ನಡ)</option>
                    <option className="bg-slate-900 text-white" value="Telugu">Telugu (తెలుగు)</option>
                    <option className="bg-slate-900 text-white" value="Tamil">Tamil (தமிழ்)</option>
                    <option className="bg-slate-900 text-white" value="Marathi">Marathi (मराठी)</option>
                    <option className="bg-slate-900 text-white" value="Bengali">Bengali (বাংলা)</option>
                    <option className="bg-slate-900 text-white" value="Malayalam">Malayalam (മലയാളം)</option>
                  </select>
                </div>
                <div className="flex flex-col">
                  <label className="text-xs font-semibold text-slate-400 mb-1">Caregiver WhatsApp Number</label>
                  <input 
                    type="text" 
                    placeholder="e.g. +91 9988776655" 
                    value={newPatient.caregiver_whatsapp} 
                    onChange={e => setNewPatient({...newPatient, caregiver_whatsapp: e.target.value})}
                    className="glass-input"
                  />
                </div>
                <div className="flex flex-col">
                  <label className="text-xs font-semibold text-slate-400 mb-1">Personalized Spoken Greeting / Audio URL</label>
                  <input 
                    type="text" 
                    placeholder="e.g. Hello Amma, hope you slept well." 
                    value={newPatient.greeting_audio_url} 
                    onChange={e => setNewPatient({...newPatient, greeting_audio_url: e.target.value})}
                    className="glass-input"
                  />
                </div>
                <button type="submit" className="w-full py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-lg text-sm transition-colors flex items-center justify-center gap-1.5">
                  <Plus className="w-4 h-4" /> Save Patient Profile
                </button>
              </form>
            </div>

            {/* Add Medication Card */}
            <div id="schedule-medication-form" className="glass-panel p-6">
              <h3 className="text-lg font-bold flex items-center gap-2 mb-4 text-white">
                <Calendar className="w-5 h-5 text-indigo-400" /> Schedule Medication
              </h3>
              <form onSubmit={handleAddMedicine} className="space-y-4">
                <div className="flex flex-col">
                  <label className="text-xs font-semibold text-slate-400 mb-1">Select Patient</label>
                  <select 
                    value={newMedicine.elderly_id} 
                    onChange={e => setNewMedicine({...newMedicine, elderly_id: e.target.value})}
                    className="glass-input bg-slate-900 border-white/10"
                  >
                    <option value="">-- Choose Patient --</option>
                    {patients.map(p => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="flex flex-col">
                    <label className="text-xs font-semibold text-slate-400 mb-1">Medication Name</label>
                    <input 
                      type="text" 
                      placeholder="Metformin" 
                      value={newMedicine.name} 
                      onChange={e => setNewMedicine({...newMedicine, name: e.target.value})}
                      className="glass-input"
                    />
                  </div>
                  <div className="flex flex-col">
                    <label className="text-xs font-semibold text-slate-400 mb-1">Dosage</label>
                    <input 
                      type="text" 
                      placeholder="1 tablet" 
                      value={newMedicine.dosage} 
                      onChange={e => setNewMedicine({...newMedicine, dosage: e.target.value})}
                      className="glass-input"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div className="flex flex-col col-span-2">
                    <label className="text-xs font-semibold text-slate-400 mb-1">Scheduled Daily Time</label>
                    <input 
                      type="text" 
                      placeholder="08:00" 
                      value={newMedicine.time} 
                      onChange={e => setNewMedicine({...newMedicine, time: e.target.value})}
                      className="glass-input font-mono"
                    />
                  </div>
                  <div className="flex flex-col">
                    <label className="text-xs font-semibold text-slate-400 mb-1">Duration</label>
                    <input 
                      type="text" 
                      placeholder="30 Days" 
                      value={newMedicine.duration} 
                      onChange={e => setNewMedicine({...newMedicine, duration: e.target.value})}
                      className="glass-input"
                    />
                  </div>
                </div>
                <div className="flex flex-col">
                  <label className="text-xs font-semibold text-slate-400 mb-1">Plain-Language description (Spoken Recognition)</label>
                  <textarea 
                    placeholder="e.g. Small white round tablet with a cross score" 
                    value={newMedicine.description} 
                    onChange={e => setNewMedicine({...newMedicine, description: e.target.value})}
                    rows="2"
                    className="glass-input resize-none"
                  />
                  <span className="text-[10px] text-slate-500 mt-1">This will be read aloud to the elderly patient during the call instead of complex medicine names.</span>
                </div>
                <button type="submit" className="w-full py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-lg text-sm transition-colors flex items-center justify-center gap-1.5">
                  <Plus className="w-4 h-4" /> Save & Schedule
                </button>
              </form>
            </div>
            
          </div>

          {/* Prescription OCR AI Scanner section */}
          <div className="glass-panel p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold flex items-center gap-2 text-white">
                <Upload className="w-5 h-5 text-indigo-400" /> AI Prescription OCR Parser
              </h3>
              <span className="text-xs bg-indigo-500/20 text-indigo-300 px-2 py-0.5 rounded-full font-medium">Vision + Gemini</span>
            </div>
            <p className="text-xs text-slate-400 mb-6">
              Upload prescription image or PDF to instantly extract medicines, dosage instructions, schedule timings, and visual descriptions.
            </p>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="border border-dashed border-white/10 rounded-xl p-6 flex flex-col items-center justify-center text-center bg-white/5 relative">
                <input 
                  type="file" 
                  id="prescription-upload" 
                  accept="image/*,application/pdf" 
                  className="hidden" 
                  onChange={(e) => setSelectedFile(e.target.files[0] || null)} 
                />
                <Upload className="w-10 h-10 text-indigo-400 mb-2" />
                {selectedFile ? (
                  <div className="space-y-2 w-full">
                    <span className="text-sm font-semibold text-emerald-400 block truncate">
                      📄 {selectedFile.name}
                    </span>
                    <span className="text-xs text-slate-400 block">
                      ({(selectedFile.size / 1024).toFixed(1)} KB)
                    </span>
                    <div className="flex gap-2 justify-center mt-2">
                      <label 
                        htmlFor="prescription-upload" 
                        className="cursor-pointer px-3 py-1.5 bg-white/5 border border-white/10 hover:bg-white/10 text-slate-300 rounded-lg text-xs font-semibold transition-all"
                      >
                        Change File
                      </label>
                      <button 
                        onClick={handleRealOCRUpload}
                        disabled={ocrLoading}
                        className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-semibold transition-all flex items-center gap-1"
                      >
                        {ocrLoading ? (
                          <><RefreshCw className="w-3 h-3 animate-spin" /> Parsing...</>
                        ) : (
                          <><Sparkles className="w-3 h-3" /> Parse File</>
                        )}
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <span className="text-sm font-semibold text-slate-200">Upload prescription file</span>
                    <span className="text-xs text-slate-500 mt-1 mb-3">PNG, JPG, PDF (Up to 5MB)</span>
                    <label 
                      htmlFor="prescription-upload" 
                      className="cursor-pointer px-4 py-2 bg-indigo-600/30 border border-indigo-500/40 text-indigo-300 hover:bg-indigo-600/40 rounded-lg text-xs font-semibold transition-all flex items-center gap-2"
                    >
                      <Plus className="w-3.5 h-3.5" /> Select File
                    </label>
                  </>
                )}
              </div>

              <div className="space-y-4">
                <div className="flex flex-col">
                  <label className="text-xs font-semibold text-slate-400 mb-1">Target Patient Profile</label>
                  <select 
                    value={ocrTargetPatientId}
                    onChange={e => setOcrTargetPatientId(e.target.value)}
                    className="glass-input bg-slate-900 border-white/10 text-sm"
                  >
                    <option value="">-- Choose Patient for parsed meds --</option>
                    {patients.map(p => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>

                <div className="p-4 bg-slate-900/60 rounded-xl border border-white/5 min-h-[120px] flex flex-col justify-center">
                  {!ocrResult ? (
                    <span className="text-xs text-slate-500 italic text-center block">OCR parse output will appear here.</span>
                  ) : (
                    <div className="space-y-3">
                      <span className="text-xs font-bold text-indigo-400 uppercase tracking-wider block">Parsed Medicines ({ocrResult.length})</span>
                      {ocrResult.map((m, idx) => (
                        <div key={idx} className="p-3 bg-white/5 rounded-lg border border-white/5 text-xs space-y-1">
                          <div className="flex justify-between items-center">
                            <span className="font-bold text-white text-sm">{m.name}</span>
                            <button 
                              onClick={() => handleFillOcrMedicine(m, idx)}
                              className="px-2.5 py-1 bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-500/40 transition-all rounded text-[11px] font-bold"
                            >
                              Fill Form
                            </button>
                          </div>
                          <div><span className="text-slate-400">Dosage:</span> <span className="text-slate-200">{m.dosage}</span></div>
                          <div><span className="text-slate-400">Time:</span> <span className="text-slate-200 font-mono">{m.time}</span></div>
                          <div><span className="text-slate-400">Description:</span> <span className="text-slate-300 italic">{m.description}</span></div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
          
        </main>

        {/* Right Side: Twilio / WhatsApp Interactive Simulator (4 cols) */}
        <aside className="lg:col-span-4 space-y-8">
          
          {/* Twilio Outbound Call Simulator widget */}
          <div className="glass-panel p-6 border-indigo-500/30 shadow-indigo-500/10">
            <div className="flex items-center justify-between mb-4 pb-3 border-b border-white/10">
              <h3 className="text-base font-bold flex items-center gap-2 text-white">
                <Phone className="w-4 h-4 text-emerald-400" /> Twilio Phone Simulator
              </h3>
              <span className="text-[10px] bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded-full font-bold uppercase tracking-wider signal-live">
                Live Simulator
              </span>
            </div>

            {activeCalls.length === 0 ? (
              <div className="p-8 border border-white/5 rounded-2xl bg-black/20 text-center text-xs text-slate-500 flex flex-col items-center justify-center space-y-2">
                <Volume2 className="w-8 h-8 text-slate-600" />
                <span>No active outbound calls ringing.</span>
                <span className="text-[10px] text-slate-600 block">Trigger a call from the medication list or wait for scheduled logs to start.</span>
              </div>
            ) : (
              activeCalls.map((call, idx) => (
                <div key={idx} className="p-4 bg-slate-900 border border-indigo-500/40 rounded-2xl space-y-4 ringing-pulse">
                  
                  {/* Dialing Screen Header */}
                  <div className="text-center space-y-1">
                    <span className="text-[10px] text-emerald-400 font-bold uppercase tracking-widest block animate-pulse">
                      📞 INCOMING REMINDER (ATTEMPT {call.attempt}/3)
                    </span>
                    <h4 className="text-lg font-bold text-white">{call.patient_name}</h4>
                    <span className="text-xs text-slate-400 font-mono">{call.patient_phone}</span>
                  </div>

                  {/* Text-to-Speech playback box */}
                  <div className="p-3 bg-white/5 rounded-xl border border-white/5 space-y-2 text-xs">
                    <div className="flex items-center gap-1.5 text-indigo-400 font-bold">
                      <Volume2 className="w-3.5 h-3.5" /> Text-to-Speech Output ({call.language}):
                    </div>
                    <p className="text-slate-300 italic">
                      &quot;{call.greeting}&quot;
                    </p>
                    <p className="text-slate-200 font-medium">
                      &quot;{call.prompt}&quot;
                    </p>
                    <p className="text-amber-300 font-semibold">
                      &quot;{call.action_prompt}&quot;
                    </p>
                  </div>

                  {/* Interactive Button Pad */}
                  <div className="grid grid-cols-3 gap-2 pt-2">
                    <button 
                      onClick={() => handleSimulatorAction(call.job_id, "CONFIRM")}
                      className="col-span-2 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-xl text-xs flex items-center justify-center gap-1 transition-all"
                    >
                      <Check className="w-4 h-4" /> Press 1 (Confirm)
                    </button>
                    <button 
                      onClick={() => handleSimulatorAction(call.job_id, "HANGUP")}
                      className="py-2.5 bg-amber-600/30 hover:bg-amber-600/50 text-amber-300 border border-amber-500/30 font-bold rounded-xl text-xs flex items-center justify-center transition-all"
                    >
                      Hangup
                    </button>
                  </div>

                  <button 
                    onClick={() => handleSimulatorAction(call.job_id, "NO_ANSWER")}
                    className="w-full py-2 bg-rose-600/20 hover:bg-rose-600/40 text-rose-300 border border-rose-500/30 rounded-xl text-xs font-semibold transition-all"
                  >
                    No Answer / Timeout
                  </button>

                </div>
              ))
            )}
          </div>

          {/* WhatsApp Caregiver Escalation Simulator Feed */}
          <div className="glass-panel p-6 border-indigo-500/10 shadow-xl">
            <div className="flex items-center justify-between mb-4 pb-3 border-b border-white/10">
              <h3 className="text-base font-bold flex items-center gap-2 text-white">
                <Send className="w-4 h-4 text-emerald-400" /> Caregiver WhatsApp alerts
              </h3>
              <span className="text-[10px] bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded-full font-bold">
                WhatsApp API
              </span>
            </div>

            {whatsappAlerts.length === 0 ? (
              <div className="p-8 border border-white/5 rounded-2xl bg-black/20 text-center text-xs text-slate-500 italic">
                No WhatsApp alerts triggered yet. If reminders fail 3 times, escalation alert displays here.
              </div>
            ) : (
              <div className="space-y-3 max-h-[300px] overflow-y-auto pr-1">
                {whatsappAlerts.map(alert => (
                  <div key={alert.id} className="p-3 bg-emerald-950/30 border border-emerald-500/20 rounded-xl text-xs space-y-1.5">
                    <div className="flex justify-between items-center text-slate-400">
                      <span className="font-bold text-emerald-400">To: {alert.to} ({alert.patient_name})</span>
                      <span className="text-[10px] font-mono">{new Date(alert.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                    </div>
                    <p className="text-slate-200 font-medium">
                      {alert.message}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* System State Machine Help Information Card */}
          <div className="p-4 bg-white/5 rounded-xl border border-white/5 space-y-3">
            <h4 className="text-xs font-bold text-white flex items-center gap-1">
              <Info className="w-3.5 h-3.5 text-indigo-400" /> Simulation Guide
            </h4>
            <ul className="text-[11px] text-slate-400 space-y-2 list-disc list-inside">
              <li>Use <strong>Trigger Call</strong> to start a voice reminder immediately.</li>
              <li>Answering and pressing 1 transitions the state machine to <strong className="text-emerald-400">CONFIRMED</strong>.</li>
              <li>Declining, hanging up, or timing out triggers retry backoff delay schedules.</li>
              <li>On the 3rd failed attempt, the alert goes to the Caregiver's WhatsApp feed, marking state as <strong className="text-rose-400">CAREGIVER_NOTIFIED</strong>.</li>
            </ul>
          </div>

        </aside>

      </div>
    </div>
  );
}
