sub init()
    m.label = m.top.findNode("label")
    m.top.observeField("message", "onMessageChanged")
end sub

sub onMessageChanged()
    if m.label <> invalid then
        m.label.text = m.top.message
    end if
end sub
