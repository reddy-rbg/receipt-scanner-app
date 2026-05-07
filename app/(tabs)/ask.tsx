import { useState, useRef } from 'react';
import {
  View, Text, ScrollView, TouchableOpacity, TextInput,
  StyleSheet, ActivityIndicator, KeyboardAvoidingView, Platform,
} from 'react-native';

const API = 'https://web-production-3605f4.up.railway.app';
const C = {
  bg:'#080810',surface:'#0f0f1a',surface2:'#16162a',
  border:'rgba(255,255,255,0.06)',
  accent:'#7c6aff',text:'#ede8ff',text2:'#7e7a9a',text3:'#3d3a55',
};

const QUICK=[
  'How much have I spent in total?',
  'Which store do I visit most?',
  'Most expensive item I bought?',
  'Show all receipts in a table',
  'How much have I saved?',
  'Compare my spending by store',
];

type Msg={role:'user'|'ai';text:string};

export default function AskScreen(){
  const [msgs,setMsgs]=useState<Msg[]>([
    {role:'ai',text:'Hi! Ask me anything about your receipts — spending, savings, store comparisons, or price history. 🧾'},
  ]);
  const [input,setInput]=useState('');
  const [loading,setLoading]=useState(false);
  const scrollRef=useRef<ScrollView>(null);

  async function ask(q:string){
    const question=q.trim();
    if(!question||loading) return;
    setInput('');
    setMsgs(p=>[...p,{role:'user',text:question}]);
    setLoading(true);
    setTimeout(()=>scrollRef.current?.scrollToEnd({animated:true}),80);
    try{
      // ✅ POST /ask with {question}, returns {answer}
      const res=await fetch(`${API}/ask`,{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({question}),
      });
      const data=await res.json();
      const answer=data.answer||data.response||'Sorry, I could not get an answer.';
      // Strip markdown for plain text display
      const plain=answer.replace(/\*\*(.+?)\*\*/g,'$1').replace(/\*(.+?)\*/g,'$1').replace(/^#{1,3} /gm,'').replace(/\|[^\n]+\|/g,'').trim();
      setMsgs(p=>[...p,{role:'ai',text:plain}]);
    }catch{
      setMsgs(p=>[...p,{role:'ai',text:'Could not connect to server. Please try again.'}]);
    }finally{
      setLoading(false);
      setTimeout(()=>scrollRef.current?.scrollToEnd({animated:true}),100);
    }
  }

  return(
    <KeyboardAvoidingView style={s.screen} behavior={Platform.OS==='ios'?'padding':undefined} keyboardVerticalOffset={90}>
      <ScrollView ref={scrollRef} style={s.chat} contentContainerStyle={s.chatContent} showsVerticalScrollIndicator={false}>

        {/* Quick questions */}
        <View style={s.quickSection}>
          <Text style={s.quickLabel}>Try asking</Text>
          <View style={s.quickWrap}>
            {QUICK.map((q,i)=>(
              <TouchableOpacity key={i} style={s.quickChip} onPress={()=>ask(q)} activeOpacity={0.7}>
                <Text style={s.quickChipTxt}>{q}</Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>

        {/* Messages */}
        {msgs.map((msg,i)=>(
          <View key={i} style={[s.bubbleWrap,msg.role==='user'?s.wrapUser:s.wrapAI]}>
            {msg.role==='ai'&&<View style={s.avatar}><Text style={{fontSize:13,color:C.accent}}>✦</Text></View>}
            <View style={[s.bubble,msg.role==='user'?s.bubbleUser:s.bubbleAI]}>
              <Text style={[s.bubbleTxt,msg.role==='user'&&{color:'#fff'}]}>{msg.text}</Text>
            </View>
          </View>
        ))}

        {loading&&(
          <View style={[s.bubbleWrap,s.wrapAI]}>
            <View style={s.avatar}><Text style={{fontSize:13,color:C.accent}}>✦</Text></View>
            <View style={s.bubbleAI}><ActivityIndicator size="small" color={C.accent}/></View>
          </View>
        )}
      </ScrollView>

      {/* Input bar */}
      <View style={s.inputBar}>
        <TextInput
          style={s.input} placeholder="Ask about your receipts..."
          placeholderTextColor={C.text3} value={input}
          onChangeText={setInput} onSubmitEditing={()=>ask(input)}
          returnKeyType="send" multiline
        />
        <TouchableOpacity
          style={[s.sendBtn,(!input.trim()||loading)&&{opacity:0.35}]}
          onPress={()=>ask(input)} disabled={!input.trim()||loading} activeOpacity={0.85}
        >
          <Text style={s.sendIcon}>↑</Text>
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const s=StyleSheet.create({
  screen:{flex:1,backgroundColor:C.bg},
  chat:{flex:1},
  chatContent:{padding:16,paddingBottom:8},
  quickSection:{marginBottom:20},
  quickLabel:{color:C.text3,fontSize:10,letterSpacing:0.5,textTransform:'uppercase',marginBottom:8},
  quickWrap:{flexDirection:'row',flexWrap:'wrap',gap:7},
  quickChip:{backgroundColor:C.surface2,borderWidth:1,borderColor:C.border,borderRadius:99,paddingHorizontal:12,paddingVertical:6},
  quickChipTxt:{color:C.text2,fontSize:12},
  bubbleWrap:{flexDirection:'row',alignItems:'flex-end',marginBottom:12,gap:8},
  wrapUser:{justifyContent:'flex-end'},
  wrapAI:{justifyContent:'flex-start'},
  avatar:{width:28,height:28,borderRadius:8,backgroundColor:'rgba(124,106,255,0.15)',alignItems:'center',justifyContent:'center',flexShrink:0},
  bubble:{maxWidth:'80%',borderRadius:16,padding:12,paddingHorizontal:14},
  bubbleUser:{backgroundColor:C.accent,borderBottomRightRadius:4,shadowColor:C.accent,shadowOpacity:0.3,shadowRadius:8},
  bubbleAI:{backgroundColor:C.surface2,borderWidth:1,borderColor:C.border,borderBottomLeftRadius:4},
  bubbleTxt:{color:C.text,fontSize:14,lineHeight:20},
  inputBar:{flexDirection:'row',alignItems:'flex-end',padding:12,paddingHorizontal:16,backgroundColor:C.surface,borderTopWidth:1,borderTopColor:C.border,gap:10},
  input:{flex:1,backgroundColor:C.surface2,borderWidth:1,borderColor:C.border,borderRadius:14,padding:12,paddingHorizontal:14,color:C.text,fontSize:14,maxHeight:100},
  sendBtn:{width:42,height:42,borderRadius:12,backgroundColor:C.accent,alignItems:'center',justifyContent:'center',shadowColor:C.accent,shadowOpacity:0.4,shadowRadius:10},
  sendIcon:{color:'#fff',fontSize:20,fontWeight:'700',lineHeight:24},
});
