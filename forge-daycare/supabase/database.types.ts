export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.5"
  }
  public: {
    Tables: {
      announcements: {
        Row: {
          audience: Database["public"]["Enums"]["audience_type"]
          author_id: string | null
          body: string
          expires_at: string | null
          id: string
          location_id: string
          pinned: boolean
          published_at: string
          title: string
        }
        Insert: {
          audience: Database["public"]["Enums"]["audience_type"]
          author_id?: string | null
          body: string
          expires_at?: string | null
          id?: string
          location_id: string
          pinned?: boolean
          published_at?: string
          title: string
        }
        Update: {
          audience?: Database["public"]["Enums"]["audience_type"]
          author_id?: string | null
          body?: string
          expires_at?: string | null
          id?: string
          location_id?: string
          pinned?: boolean
          published_at?: string
          title?: string
        }
        Relationships: [
          {
            foreignKeyName: "announcements_author_id_fkey"
            columns: ["author_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "announcements_location_id_fkey"
            columns: ["location_id"]
            isOneToOne: false
            referencedRelation: "locations"
            referencedColumns: ["id"]
          },
        ]
      }
      attendance: {
        Row: {
          attendance_date: string
          checked_in_at: string
          checked_in_by: string | null
          checked_out_at: string | null
          checked_out_by: string | null
          child_id: string
          id: string
          notes: string | null
          status: Database["public"]["Enums"]["attendance_status"]
        }
        Insert: {
          attendance_date?: string
          checked_in_at?: string
          checked_in_by?: string | null
          checked_out_at?: string | null
          checked_out_by?: string | null
          child_id: string
          id?: string
          notes?: string | null
          status?: Database["public"]["Enums"]["attendance_status"]
        }
        Update: {
          attendance_date?: string
          checked_in_at?: string
          checked_in_by?: string | null
          checked_out_at?: string | null
          checked_out_by?: string | null
          child_id?: string
          id?: string
          notes?: string | null
          status?: Database["public"]["Enums"]["attendance_status"]
        }
        Relationships: [
          {
            foreignKeyName: "attendance_checked_in_by_fkey"
            columns: ["checked_in_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "attendance_checked_out_by_fkey"
            columns: ["checked_out_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "attendance_child_id_fkey"
            columns: ["child_id"]
            isOneToOne: false
            referencedRelation: "children"
            referencedColumns: ["id"]
          },
        ]
      }
      children: {
        Row: {
          active: boolean
          allergies: string | null
          avatar_path: string | null
          birth_date: string
          classroom_id: string | null
          created_at: string
          enrollment_date: string
          first_name: string
          guardian_profile_id: string | null
          id: string
          last_name: string
          location_id: string
          medical_notes: string | null
          pickup_notes: string | null
          preferred_name: string | null
        }
        Insert: {
          active?: boolean
          allergies?: string | null
          avatar_path?: string | null
          birth_date: string
          classroom_id?: string | null
          created_at?: string
          enrollment_date?: string
          first_name: string
          guardian_profile_id?: string | null
          id?: string
          last_name: string
          location_id: string
          medical_notes?: string | null
          pickup_notes?: string | null
          preferred_name?: string | null
        }
        Update: {
          active?: boolean
          allergies?: string | null
          avatar_path?: string | null
          birth_date?: string
          classroom_id?: string | null
          created_at?: string
          enrollment_date?: string
          first_name?: string
          guardian_profile_id?: string | null
          id?: string
          last_name?: string
          location_id?: string
          medical_notes?: string | null
          pickup_notes?: string | null
          preferred_name?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "children_classroom_id_fkey"
            columns: ["classroom_id"]
            isOneToOne: false
            referencedRelation: "classrooms"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "children_guardian_profile_id_fkey"
            columns: ["guardian_profile_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "children_location_id_fkey"
            columns: ["location_id"]
            isOneToOne: false
            referencedRelation: "locations"
            referencedColumns: ["id"]
          },
        ]
      }
      classrooms: {
        Row: {
          active: boolean
          age_group: string
          capacity: number
          color: string
          id: string
          location_id: string
          name: string
          ratio_children: number
        }
        Insert: {
          active?: boolean
          age_group: string
          capacity: number
          color?: string
          id?: string
          location_id: string
          name: string
          ratio_children?: number
        }
        Update: {
          active?: boolean
          age_group?: string
          capacity?: number
          color?: string
          id?: string
          location_id?: string
          name?: string
          ratio_children?: number
        }
        Relationships: [
          {
            foreignKeyName: "classrooms_location_id_fkey"
            columns: ["location_id"]
            isOneToOne: false
            referencedRelation: "locations"
            referencedColumns: ["id"]
          },
        ]
      }
      daily_logs: {
        Row: {
          activity: string | null
          author_id: string | null
          bathroom: string | null
          child_id: string
          created_at: string
          id: string
          log_date: string
          meal: string | null
          mood: string | null
          nap_minutes: number | null
          notes: string | null
          occurred_at: string
        }
        Insert: {
          activity?: string | null
          author_id?: string | null
          bathroom?: string | null
          child_id: string
          created_at?: string
          id?: string
          log_date?: string
          meal?: string | null
          mood?: string | null
          nap_minutes?: number | null
          notes?: string | null
          occurred_at?: string
        }
        Update: {
          activity?: string | null
          author_id?: string | null
          bathroom?: string | null
          child_id?: string
          created_at?: string
          id?: string
          log_date?: string
          meal?: string | null
          mood?: string | null
          nap_minutes?: number | null
          notes?: string | null
          occurred_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "daily_logs_author_id_fkey"
            columns: ["author_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "daily_logs_child_id_fkey"
            columns: ["child_id"]
            isOneToOne: false
            referencedRelation: "children"
            referencedColumns: ["id"]
          },
        ]
      }
      guardian_children: {
        Row: {
          child_id: string
          guardian_id: string
          primary_guardian: boolean
        }
        Insert: {
          child_id: string
          guardian_id: string
          primary_guardian?: boolean
        }
        Update: {
          child_id?: string
          guardian_id?: string
          primary_guardian?: boolean
        }
        Relationships: [
          {
            foreignKeyName: "guardian_children_child_id_fkey"
            columns: ["child_id"]
            isOneToOne: false
            referencedRelation: "children"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "guardian_children_guardian_id_fkey"
            columns: ["guardian_id"]
            isOneToOne: false
            referencedRelation: "guardians"
            referencedColumns: ["id"]
          },
        ]
      }
      guardians: {
        Row: {
          authorized_pickup: boolean
          emergency_contact: boolean
          id: string
          location_id: string
          profile_id: string
          relationship_label: string | null
        }
        Insert: {
          authorized_pickup?: boolean
          emergency_contact?: boolean
          id?: string
          location_id: string
          profile_id: string
          relationship_label?: string | null
        }
        Update: {
          authorized_pickup?: boolean
          emergency_contact?: boolean
          id?: string
          location_id?: string
          profile_id?: string
          relationship_label?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "guardians_location_id_fkey"
            columns: ["location_id"]
            isOneToOne: false
            referencedRelation: "locations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "guardians_profile_id_fkey"
            columns: ["profile_id"]
            isOneToOne: true
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      incident_reports: {
        Row: {
          action_taken: string
          child_id: string
          created_at: string
          description: string
          id: string
          location_detail: string
          occurred_at: string
          parent_notified_at: string | null
          reporter_id: string | null
          severity: Database["public"]["Enums"]["incident_severity"]
          witness_names: string | null
        }
        Insert: {
          action_taken: string
          child_id: string
          created_at?: string
          description: string
          id?: string
          location_detail: string
          occurred_at: string
          parent_notified_at?: string | null
          reporter_id?: string | null
          severity: Database["public"]["Enums"]["incident_severity"]
          witness_names?: string | null
        }
        Update: {
          action_taken?: string
          child_id?: string
          created_at?: string
          description?: string
          id?: string
          location_detail?: string
          occurred_at?: string
          parent_notified_at?: string | null
          reporter_id?: string | null
          severity?: Database["public"]["Enums"]["incident_severity"]
          witness_names?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "incident_reports_child_id_fkey"
            columns: ["child_id"]
            isOneToOne: false
            referencedRelation: "children"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "incident_reports_reporter_id_fkey"
            columns: ["reporter_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      invoices: {
        Row: {
          amount: number
          child_id: string | null
          created_at: string
          description: string
          due_on: string
          guardian_id: string
          id: string
          invoice_number: string
          issued_on: string
          location_id: string
          paid_at: string | null
          payments: Json
          status: Database["public"]["Enums"]["invoice_status"]
        }
        Insert: {
          amount: number
          child_id?: string | null
          created_at?: string
          description: string
          due_on: string
          guardian_id: string
          id?: string
          invoice_number: string
          issued_on: string
          location_id: string
          paid_at?: string | null
          payments?: Json
          status?: Database["public"]["Enums"]["invoice_status"]
        }
        Update: {
          amount?: number
          child_id?: string | null
          created_at?: string
          description?: string
          due_on?: string
          guardian_id?: string
          id?: string
          invoice_number?: string
          issued_on?: string
          location_id?: string
          paid_at?: string | null
          payments?: Json
          status?: Database["public"]["Enums"]["invoice_status"]
        }
        Relationships: [
          {
            foreignKeyName: "invoices_child_id_fkey"
            columns: ["child_id"]
            isOneToOne: false
            referencedRelation: "children"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "invoices_guardian_id_fkey"
            columns: ["guardian_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "invoices_location_id_fkey"
            columns: ["location_id"]
            isOneToOne: false
            referencedRelation: "locations"
            referencedColumns: ["id"]
          },
        ]
      }
      locations: {
        Row: {
          address: string | null
          closes_at: string | null
          created_at: string
          id: string
          name: string
          opens_at: string | null
          phone: string | null
          timezone: string
        }
        Insert: {
          address?: string | null
          closes_at?: string | null
          created_at?: string
          id?: string
          name: string
          opens_at?: string | null
          phone?: string | null
          timezone?: string
        }
        Update: {
          address?: string | null
          closes_at?: string | null
          created_at?: string
          id?: string
          name?: string
          opens_at?: string | null
          phone?: string | null
          timezone?: string
        }
        Relationships: []
      }
      login_id_counters: {
        Row: {
          account_kind: string
          next_number: number
        }
        Insert: {
          account_kind: string
          next_number: number
        }
        Update: {
          account_kind?: string
          next_number?: number
        }
        Relationships: []
      }
      message_threads: {
        Row: {
          created_at: string
          created_by: string | null
          id: string
          kind: string
          location_id: string
          title: string | null
        }
        Insert: {
          created_at?: string
          created_by?: string | null
          id?: string
          kind?: string
          location_id: string
          title?: string | null
        }
        Update: {
          created_at?: string
          created_by?: string | null
          id?: string
          kind?: string
          location_id?: string
          title?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "message_threads_created_by_fkey"
            columns: ["created_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "message_threads_location_id_fkey"
            columns: ["location_id"]
            isOneToOne: false
            referencedRelation: "locations"
            referencedColumns: ["id"]
          },
        ]
      }
      messages: {
        Row: {
          attachment_path: string | null
          body: string
          created_at: string
          id: string
          reactions: Json
          sender_id: string | null
          thread_id: string
        }
        Insert: {
          attachment_path?: string | null
          body?: string
          created_at?: string
          id?: string
          reactions?: Json
          sender_id?: string | null
          thread_id: string
        }
        Update: {
          attachment_path?: string | null
          body?: string
          created_at?: string
          id?: string
          reactions?: Json
          sender_id?: string | null
          thread_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "messages_sender_id_fkey"
            columns: ["sender_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "messages_thread_id_fkey"
            columns: ["thread_id"]
            isOneToOne: false
            referencedRelation: "message_threads"
            referencedColumns: ["id"]
          },
        ]
      }
      notifications: {
        Row: {
          body: string
          created_at: string
          id: string
          kind: string
          link: string | null
          profile_id: string
          read_at: string | null
          title: string
        }
        Insert: {
          body: string
          created_at?: string
          id?: string
          kind: string
          link?: string | null
          profile_id: string
          read_at?: string | null
          title: string
        }
        Update: {
          body?: string
          created_at?: string
          id?: string
          kind?: string
          link?: string | null
          profile_id?: string
          read_at?: string | null
          title?: string
        }
        Relationships: [
          {
            foreignKeyName: "notifications_profile_id_fkey"
            columns: ["profile_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      payment_methods: {
        Row: {
          brand: string
          expires_month: number | null
          expires_year: number | null
          guardian_id: string
          id: string
          is_default: boolean
          last_four: string
        }
        Insert: {
          brand: string
          expires_month?: number | null
          expires_year?: number | null
          guardian_id: string
          id?: string
          is_default?: boolean
          last_four: string
        }
        Update: {
          brand?: string
          expires_month?: number | null
          expires_year?: number | null
          guardian_id?: string
          id?: string
          is_default?: boolean
          last_four?: string
        }
        Relationships: [
          {
            foreignKeyName: "payment_methods_guardian_id_fkey"
            columns: ["guardian_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      payments: {
        Row: {
          amount: number
          created_at: string
          id: string
          idempotency_key: string | null
          invoice_id: string
          method_label: string
          paid_at: string
          provider: string
          provider_reference: string | null
          recorded_by: string | null
          reference: string | null
          status: string
        }
        Insert: {
          amount: number
          created_at?: string
          id?: string
          idempotency_key?: string | null
          invoice_id: string
          method_label: string
          paid_at?: string
          provider?: string
          provider_reference?: string | null
          recorded_by?: string | null
          reference?: string | null
          status?: string
        }
        Update: {
          amount?: number
          created_at?: string
          id?: string
          idempotency_key?: string | null
          invoice_id?: string
          method_label?: string
          paid_at?: string
          provider?: string
          provider_reference?: string | null
          recorded_by?: string | null
          reference?: string | null
          status?: string
        }
        Relationships: [
          {
            foreignKeyName: "payments_invoice_id_fkey"
            columns: ["invoice_id"]
            isOneToOne: false
            referencedRelation: "invoices"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "payments_recorded_by_fkey"
            columns: ["recorded_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      payroll_records: {
        Row: {
          deductions: number
          gross_pay: number
          id: string
          net_pay: number | null
          overtime_hours: number
          paid_at: string | null
          payment_reference: string | null
          period_end: string
          period_start: string
          regular_hours: number
          staff_id: string
          status: string
        }
        Insert: {
          deductions?: number
          gross_pay?: number
          id?: string
          net_pay?: number | null
          overtime_hours?: number
          paid_at?: string | null
          payment_reference?: string | null
          period_end: string
          period_start: string
          regular_hours?: number
          staff_id: string
          status?: string
        }
        Update: {
          deductions?: number
          gross_pay?: number
          id?: string
          net_pay?: number | null
          overtime_hours?: number
          paid_at?: string | null
          payment_reference?: string | null
          period_end?: string
          period_start?: string
          regular_hours?: number
          staff_id?: string
          status?: string
        }
        Relationships: [
          {
            foreignKeyName: "payroll_records_staff_id_fkey"
            columns: ["staff_id"]
            isOneToOne: false
            referencedRelation: "staff_members"
            referencedColumns: ["id"]
          },
        ]
      }
      photo_posts: {
        Row: {
          caption: string | null
          child_id: string
          created_at: string
          id: string
          storage_path: string
          taken_at: string
          uploaded_by: string | null
        }
        Insert: {
          caption?: string | null
          child_id: string
          created_at?: string
          id?: string
          storage_path: string
          taken_at?: string
          uploaded_by?: string | null
        }
        Update: {
          caption?: string | null
          child_id?: string
          created_at?: string
          id?: string
          storage_path?: string
          taken_at?: string
          uploaded_by?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "photo_posts_child_id_fkey"
            columns: ["child_id"]
            isOneToOne: false
            referencedRelation: "children"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "photo_posts_uploaded_by_fkey"
            columns: ["uploaded_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      profiles: {
        Row: {
          active: boolean
          auth_email: string | null
          avatar_path: string | null
          created_at: string
          display_name: string | null
          first_name: string
          id: string
          last_name: string
          location_id: string | null
          login_id: string | null
          permissions: Json
          phone: string | null
          role: Database["public"]["Enums"]["app_role"]
          updated_at: string
        }
        Insert: {
          active?: boolean
          auth_email?: string | null
          avatar_path?: string | null
          created_at?: string
          display_name?: string | null
          first_name?: string
          id: string
          last_name?: string
          location_id?: string | null
          login_id?: string | null
          permissions?: Json
          phone?: string | null
          role?: Database["public"]["Enums"]["app_role"]
          updated_at?: string
        }
        Update: {
          active?: boolean
          auth_email?: string | null
          avatar_path?: string | null
          created_at?: string
          display_name?: string | null
          first_name?: string
          id?: string
          last_name?: string
          location_id?: string | null
          login_id?: string | null
          permissions?: Json
          phone?: string | null
          role?: Database["public"]["Enums"]["app_role"]
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "profiles_location_id_fkey"
            columns: ["location_id"]
            isOneToOne: false
            referencedRelation: "locations"
            referencedColumns: ["id"]
          },
        ]
      }
      staff_classrooms: {
        Row: {
          classroom_id: string
          staff_id: string
        }
        Insert: {
          classroom_id: string
          staff_id: string
        }
        Update: {
          classroom_id?: string
          staff_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "staff_classrooms_classroom_id_fkey"
            columns: ["classroom_id"]
            isOneToOne: false
            referencedRelation: "classrooms"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "staff_classrooms_staff_id_fkey"
            columns: ["staff_id"]
            isOneToOne: false
            referencedRelation: "staff_members"
            referencedColumns: ["id"]
          },
        ]
      }
      staff_members: {
        Row: {
          certifications: Json
          color: string
          hire_date: string | null
          hourly_rate: number | null
          id: string
          job_title: string
          location_id: string
          profile_id: string
        }
        Insert: {
          certifications?: Json
          color?: string
          hire_date?: string | null
          hourly_rate?: number | null
          id?: string
          job_title: string
          location_id: string
          profile_id: string
        }
        Update: {
          certifications?: Json
          color?: string
          hire_date?: string | null
          hourly_rate?: number | null
          id?: string
          job_title?: string
          location_id?: string
          profile_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "staff_members_location_id_fkey"
            columns: ["location_id"]
            isOneToOne: false
            referencedRelation: "locations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "staff_members_profile_id_fkey"
            columns: ["profile_id"]
            isOneToOne: true
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      staff_schedules: {
        Row: {
          end_time: string
          id: string
          staff_id: string
          start_time: string
          weekday: number
        }
        Insert: {
          end_time: string
          id?: string
          staff_id: string
          start_time: string
          weekday: number
        }
        Update: {
          end_time?: string
          id?: string
          staff_id?: string
          start_time?: string
          weekday?: number
        }
        Relationships: [
          {
            foreignKeyName: "staff_schedules_staff_id_fkey"
            columns: ["staff_id"]
            isOneToOne: false
            referencedRelation: "staff_members"
            referencedColumns: ["id"]
          },
        ]
      }
      staff_shifts: {
        Row: {
          clocked_in_at: string
          clocked_out_at: string | null
          created_at: string
          id: string
          notes: string | null
          staff_id: string
        }
        Insert: {
          clocked_in_at?: string
          clocked_out_at?: string | null
          created_at?: string
          id?: string
          notes?: string | null
          staff_id: string
        }
        Update: {
          clocked_in_at?: string
          clocked_out_at?: string | null
          created_at?: string
          id?: string
          notes?: string | null
          staff_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "staff_shifts_staff_id_fkey"
            columns: ["staff_id"]
            isOneToOne: false
            referencedRelation: "staff_members"
            referencedColumns: ["id"]
          },
        ]
      }
      thread_participants: {
        Row: {
          last_read_at: string | null
          profile_id: string
          thread_id: string
        }
        Insert: {
          last_read_at?: string | null
          profile_id: string
          thread_id: string
        }
        Update: {
          last_read_at?: string | null
          profile_id?: string
          thread_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "thread_participants_profile_id_fkey"
            columns: ["profile_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "thread_participants_thread_id_fkey"
            columns: ["thread_id"]
            isOneToOne: false
            referencedRelation: "message_threads"
            referencedColumns: ["id"]
          },
        ]
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      allocate_login_id: {
        Args: { p_role: Database["public"]["Enums"]["app_role"] }
        Returns: string
      }
      can_access_child: { Args: { target_child: string }; Returns: boolean }
      is_thread_participant: {
        Args: { target_thread: string }
        Returns: boolean
      }
      mark_payroll_paid: {
        Args: { p_paid_at?: string; p_payroll_id: string; p_reference?: string }
        Returns: {
          deductions: number
          gross_pay: number
          id: string
          net_pay: number | null
          overtime_hours: number
          paid_at: string | null
          payment_reference: string | null
          period_end: string
          period_start: string
          regular_hours: number
          staff_id: string
          status: string
        }
        SetofOptions: {
          from: "*"
          to: "payroll_records"
          isOneToOne: true
          isSetofReturn: false
        }
      }
      my_location: { Args: never; Returns: string }
      my_role: { Args: never; Returns: Database["public"]["Enums"]["app_role"] }
      my_staff_id: { Args: never; Returns: string }
      record_invoice_payment: {
        Args: {
          p_amount: number
          p_idempotency_key?: string
          p_invoice_id: string
          p_method_label: string
          p_paid_at?: string
          p_provider?: string
          p_provider_reference?: string
          p_reference?: string
        }
        Returns: {
          amount: number
          created_at: string
          id: string
          idempotency_key: string | null
          invoice_id: string
          method_label: string
          paid_at: string
          provider: string
          provider_reference: string | null
          recorded_by: string | null
          reference: string | null
          status: string
        }
        SetofOptions: {
          from: "*"
          to: "payments"
          isOneToOne: true
          isSetofReturn: false
        }
      }
    }
    Enums: {
      app_role: "parent" | "staff" | "manager" | "admin"
      attendance_status: "present" | "completed"
      audience_type: "everyone" | "parents" | "staff"
      incident_severity: "minor" | "moderate" | "serious"
      invoice_status: "draft" | "due" | "paid" | "void" | "overdue"
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {
      app_role: ["parent", "staff", "manager", "admin"],
      attendance_status: ["present", "completed"],
      audience_type: ["everyone", "parents", "staff"],
      incident_severity: ["minor", "moderate", "serious"],
      invoice_status: ["draft", "due", "paid", "void", "overdue"],
    },
  },
} as const
